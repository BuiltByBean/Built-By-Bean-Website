import json
import requests
import boto3
from datetime import datetime, timezone, date, timedelta
from flask import current_app

from models import db, ServiceProvider, ServiceMapping, ServiceCostEntry, Expense


def _get_credentials(provider):
    if not provider.credentials_json:
        return {}
    try:
        return json.loads(provider.credentials_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _find_mapping(provider_id, resource_identifier):
    return ServiceMapping.query.filter_by(
        provider_id=provider_id,
        resource_identifier=resource_identifier,
        is_active=True,
    ).all()


def _existing_entry(provider_id, resource_id, period_start, period_end, mapping_id=None):
    return ServiceCostEntry.query.filter_by(
        provider_id=provider_id,
        resource_identifier=resource_id,
        period_start=period_start,
        period_end=period_end,
        mapping_id=mapping_id,
    ).first()


def _month_bounds(when=None):
    """The calendar month `when` falls in, first and last day inclusive.

    Every sync used to end its period at today. A daily run therefore invented
    a new period each day, each holding the month to date, and because the
    period was part of the key nothing ever matched what yesterday wrote. The
    same spend booked itself over and over. A stable month is the single thing
    that makes running this on a schedule safe.
    """
    when = when or date.today()
    first = when.replace(day=1)
    return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def _sync_expense(cost_entry, mapping):
    """Keep an Expense in step with a cost entry, creating one if absent.

    An unallocated cost gets an expense too, carrying no client. It is money
    the business spent whether or not anybody has said which client it was
    for, and refusing to book it is why the ledger contained nothing but hand
    typed rows while four vendors were syncing happily.

    Updates rather than inserts on a second run, because the entry it mirrors
    is itself updated in place as the month accumulates.
    """
    expense = cost_entry.expense
    if expense is None:
        expense = Expense(category="service_cost")
        db.session.add(expense)
    expense.client_id = mapping.client_id if mapping else None
    expense.project_id = mapping.project_id if mapping else None
    expense.amount = cost_entry.allocated_amount
    expense.description = cost_entry.description
    expense.date = cost_entry.period_end
    db.session.flush()
    cost_entry.expense_id = expense.id
    return expense


# ── Main Sync Dispatcher ────────────────────────────────────


def sync_all_providers():
    """Sync every active provider. Returns [(name, count, error), ...].

    One provider's failure does not stop the others: `sync_provider` records
    the error against the provider and returns it rather than raising, so a
    Twilio outage cannot cost you a month of Cloudflare charges.
    """
    results = []
    for provider in ServiceProvider.query.filter_by(is_active=True).order_by(
        ServiceProvider.name
    ).all():
        count, error = sync_provider(provider.id)
        results.append((provider.name, count, error))
    return results


def sync_provider(provider_id):
    provider = db.session.get(ServiceProvider, provider_id)
    if not provider or not provider.is_active:
        return 0, "Provider not found or inactive"

    sync_funcs = {
        "aws": _sync_aws,
        "railway": _sync_railway,
        "twilio": _sync_twilio,
        "cloudflare": _sync_cloudflare,
    }

    func = sync_funcs.get(provider.name)
    if not func:
        return 0, f"Unknown provider type: {provider.name}"

    try:
        count = func(provider)
        provider.last_sync_at = datetime.now(timezone.utc)
        provider.sync_error = None
        db.session.commit()
        return count, None
    except Exception as e:
        provider.sync_error = str(e)
        provider.last_sync_at = datetime.now(timezone.utc)
        db.session.commit()
        return 0, str(e)


# ── AWS Cost Explorer ───────────────────────────────────────


def _sync_aws(provider):
    creds = _get_credentials(provider)
    region = creds.get("region", "us-east-2")
    key_id = creds.get("aws_access_key_id")
    secret = creds.get("aws_secret_access_key")

    ce = boto3.client("ce", region_name=region,
                       aws_access_key_id=key_id, aws_secret_access_key=secret)

    end = date.today()
    start = end - timedelta(days=30)

    # 1. Get total cost by service
    response = ce.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    count = 0
    s3_total = 0

    for result in response.get("ResultsByTime", []):
        p_start = date.fromisoformat(result["TimePeriod"]["Start"])
        p_end = date.fromisoformat(result["TimePeriod"]["End"])

        for group in result.get("Groups", []):
            service_name = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            if amount <= 0:
                continue

            if "S3" in service_name or "Storage Service" in service_name:
                s3_total = amount
                continue  # handle S3 separately below

            resource_id = f"aws:{service_name}"
            count += _record_cost_entry(provider, resource_id, p_start, p_end,
                                        amount, f"AWS {service_name}", group)

    # 2. Break down S3 costs by bucket using CloudWatch storage metrics
    if s3_total > 0:
        p_start = start.replace(day=1)
        p_end = end
        count += _sync_aws_s3_by_bucket(provider, creds, s3_total, p_start, p_end)

    db.session.commit()
    return count


def _sync_aws_s3_by_bucket(provider, creds, s3_total, p_start, p_end):
    region = creds.get("region", "us-east-2")
    s3 = boto3.client("s3", region_name=region,
                       aws_access_key_id=creds.get("aws_access_key_id"),
                       aws_secret_access_key=creds.get("aws_secret_access_key"))
    cw = boto3.client("cloudwatch", region_name=region,
                       aws_access_key_id=creds.get("aws_access_key_id"),
                       aws_secret_access_key=creds.get("aws_secret_access_key"))

    # List all buckets
    try:
        buckets = s3.list_buckets().get("Buckets", [])
    except Exception:
        buckets = []

    if not buckets:
        resource_id = "aws-s3:total"
        if not _existing_entry(provider.id, resource_id, p_start, p_end):
            return _record_cost_entry(provider, resource_id, p_start, p_end,
                                      s3_total, "AWS S3 Total", {})
        return 0

    # Get storage size for each bucket via CloudWatch
    bucket_sizes = {}
    now = datetime.now(timezone.utc)
    for bucket in buckets:
        name = bucket["Name"]
        try:
            resp = cw.get_metric_statistics(
                Namespace="AWS/S3",
                MetricName="BucketSizeBytes",
                Dimensions=[
                    {"Name": "BucketName", "Value": name},
                    {"Name": "StorageType", "Value": "StandardStorage"},
                ],
                StartTime=now - timedelta(days=3),
                EndTime=now,
                Period=86400,
                Statistics=["Average"],
            )
            datapoints = resp.get("Datapoints", [])
            if datapoints:
                bucket_sizes[name] = max(dp["Average"] for dp in datapoints)
            else:
                bucket_sizes[name] = 0
        except Exception:
            bucket_sizes[name] = 0

    total_size = sum(bucket_sizes.values())
    if total_size <= 0:
        # Can't determine proportions, split evenly
        total_size = len(buckets)
        bucket_sizes = {b["Name"]: 1 for b in buckets}

    count = 0
    for bucket_name, size in bucket_sizes.items():
        proportion = size / total_size if total_size > 0 else 0
        bucket_cost = round(s3_total * proportion, 4)
        if bucket_cost <= 0:
            continue

        resource_id = f"aws-s3:{bucket_name}"
        count += _record_cost_entry(
            provider, resource_id, p_start, p_end, bucket_cost,
            f"AWS S3 - {bucket_name}",
            {"bucket": bucket_name, "size_bytes": size, "proportion": proportion},
        )

    return count


def _record_cost_entry(provider, resource_id, p_start, p_end, amount, desc_prefix, raw_data):
    """Write, or correct, the cost of one resource for one period.

    Upsert rather than insert. A month to date figure grows all month, so a
    daily sync has to correct the row it wrote yesterday rather than stack
    another one beside it. The callers no longer skip a period they have
    already seen, for the same reason.

    One row per mapping when the resource is allocated and one unallocated row
    when it is not, with an Expense against every one of them either way.
    """
    month_label = p_start.strftime('%b %Y')
    description = f"{desc_prefix} ({month_label})"

    # `or [None]` is the unallocated case: one pass, no mapping, no client.
    for mapping in _find_mapping(provider.id, resource_id) or [None]:
        share = (mapping.split_percentage or 0) / 100.0 if mapping else 1.0
        entry = _existing_entry(provider.id, resource_id, p_start, p_end,
                                mapping.id if mapping else None)
        if entry is None:
            entry = ServiceCostEntry(
                provider_id=provider.id,
                mapping_id=mapping.id if mapping else None,
                resource_identifier=resource_id,
                period_start=p_start,
                period_end=p_end,
            )
            db.session.add(entry)
        entry.raw_amount = amount
        entry.allocated_amount = round(amount * share, 2)
        entry.description = description if mapping else f"{description} [unallocated]"
        entry.raw_data_json = json.dumps(raw_data) if raw_data else None
        db.session.flush()
        _sync_expense(entry, mapping)

    return len(_find_mapping(provider.id, resource_id) or [None])


# ── Railway ─────────────────────────────────────────────────


def _sync_railway(provider):
    creds = _get_credentials(provider)
    token = creds.get("api_token", "")
    if not token:
        raise ValueError("Railway API token not configured")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = "https://backboard.railway.com/graphql/v2"

    # Get all projects (Railway public API schema)
    query = """
    query {
        projects {
            edges {
                node {
                    id
                    name
                    description
                    createdAt
                }
            }
        }
    }
    """
    resp = requests.post(url, json={"query": query}, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        error_msg = data["errors"][0].get("message", "Unknown error") if data["errors"] else "Unknown error"
        raise ValueError(f"Railway API error: {error_msg}")

    projects = data.get("data", {}).get("projects", {}).get("edges", [])

    # Railway's API will not tell you what you are spending. Its
    # MetricMeasurement enum is CPU_USAGE, MEMORY_USAGE_GB, DISK_USAGE_GB,
    # NETWORK_TX_GB and friends, and not one value in it is denominated in
    # money. Probed 2026-08-31 with the account's own token; `me` and the
    # workspace queries are Not Authorized for a project token, so the
    # workspace level billing is out of reach as well.
    #
    # So the account's monthly figure is the one on the provider, set by hand
    # once, and this books it for the calendar month. Per project splitting is
    # still available through mappings with their own monthly_cost, for anyone
    # who wants it later.
    p_start, p_end = _month_bounds()
    count = 0

    flat = provider.monthly_cost or 0
    if flat > 0:
        count += _record_cost_entry(
            provider, "railway:account", p_start, p_end, flat,
            "Railway", {"projects": len(projects)},
        )

    for edge in projects:
        node = edge.get("node", {})
        resource_id = f"railway:{node.get('id', '')}"
        project_name = node.get("name", "Unknown")

        for mapping in _find_mapping(provider.id, resource_id):
            cost = mapping.monthly_cost or 0
            if cost <= 0:
                continue
            count += _record_cost_entry(provider, resource_id, p_start, p_end,
                                        cost, f"Railway - {project_name}", node)
            break  # _record_cost_entry already writes a row per mapping

    db.session.commit()
    return count


# ── Twilio ──────────────────────────────────────────────────


def _sync_twilio(provider):
    creds = _get_credentials(provider)
    account_sid = creds.get("account_sid", "")
    auth_token = creds.get("auth_token", "")
    if not account_sid or not auth_token:
        raise ValueError("Twilio credentials not configured")

    now = date.today()
    start = now.replace(day=1)

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Usage/Records/Monthly.json"
    params = {"StartDate": start.isoformat(), "EndDate": now.isoformat()}

    resp = requests.get(url, params=params, auth=(account_sid, auth_token), timeout=30)
    resp.raise_for_status()
    data = resp.json()

    records = data.get("usage_records", [])

    count = 0
    for record in records:
        category = record.get("category", "unknown")
        price = float(record.get("price", 0) or 0)
        if price <= 0:
            continue

        resource_id = f"twilio:{category}"
        p_start = date.fromisoformat(record.get("start_date", start.isoformat()))
        p_end = date.fromisoformat(record.get("end_date", now.isoformat()))

        description_text = record.get("description", category)

        count += _record_cost_entry(provider, resource_id, p_start, p_end,
                                    price, f"Twilio - {description_text}", record)

    db.session.commit()
    return count


# ── Cloudflare ──────────────────────────────────────────────


def _sync_cloudflare(provider):
    creds = _get_credentials(provider)
    api_token = creds.get("api_token", "")
    account_id = creds.get("account_id", "")
    if not api_token or not account_id:
        raise ValueError("Cloudflare credentials not configured")

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    # Get zones for this account
    zones_url = f"https://api.cloudflare.com/client/v4/zones?account.id={account_id}&per_page=50"
    resp = requests.get(zones_url, headers=headers, timeout=30)
    resp.raise_for_status()
    zones_data = resp.json()

    if not zones_data.get("success"):
        errors = zones_data.get("errors", [])
        raise ValueError(f"Cloudflare API error: {errors}")

    zones = zones_data.get("result", [])

    # Get billing history
    billing_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/billing/history?per_page=20&order=occurred_at&direction=desc"
    resp2 = requests.get(billing_url, headers=headers, timeout=30)
    resp2.raise_for_status()
    billing_data = resp2.json()

    # Zone plan charges are recurring, so they belong to the current calendar
    # month. Billing history items carry their own date and override this.
    p_start, p_end = _month_bounds()

    count = 0

    # Process billing items
    if billing_data.get("success"):
        for item in billing_data.get("result", []):
            amount = float(item.get("amount", 0) or 0)
            if amount <= 0:
                continue

            item_id = item.get("id", "unknown")
            description = item.get("description") or f"{item.get('type', 'charge')} {item.get('receipt_id', '')}".strip()
            resource_id = f"cloudflare:{item_id}"

            # A charge belongs to the month it happened in, not the month the
            # sync happened to run in. This used to stamp every charge with
            # today, which filed an April invoice under July and made the
            # ledger disagree with the card statement.
            occurred = item.get("occurred_at") or item.get("occured_at")
            when = date.fromisoformat(occurred[:10]) if occurred else date.today()
            c_start, c_end = _month_bounds(when)

            count += _record_cost_entry(provider, resource_id, c_start, c_end,
                                        amount, f"Cloudflare - {description}", item)

    # Also track per-zone as resources (even if free) so they can be mapped
    for zone in zones:
        zone_id = zone.get("id", "")
        zone_name = zone.get("name", "")
        plan = zone.get("plan", {})
        plan_price = float(plan.get("price", 0) or 0)

        resource_id = f"cloudflare-zone:{zone_id}"

        if plan_price <= 0:
            continue

        count += _record_cost_entry(provider, resource_id, p_start, p_end,
                                    plan_price, f"Cloudflare - {zone_name}", zone)

    db.session.commit()
    return count


# ── List Resources (for mapping UI) ────────────────────────


def list_provider_resources(provider):
    creds = _get_credentials(provider)
    resources = []

    try:
        if provider.name == "aws":
            s3 = boto3.client(
                "s3",
                aws_access_key_id=creds.get("aws_access_key_id"),
                aws_secret_access_key=creds.get("aws_secret_access_key"),
                region_name=creds.get("region", "us-east-2"),
            )
            buckets = s3.list_buckets().get("Buckets", [])
            for b in buckets:
                resources.append({
                    "id": f"aws-s3:{b['Name']}",
                    "label": f"S3 Bucket: {b['Name']}",
                })
            for svc in ["Amazon Route 53", "Amazon CloudFront",
                        "AWS Lambda", "Amazon EC2", "AWS Key Management Service"]:
                resources.append({"id": f"aws:{svc}", "label": svc})

        elif provider.name == "railway":
            token = creds.get("api_token", "")
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            query = '{ projects { edges { node { id name } } } }'
            resp = requests.post("https://backboard.railway.com/graphql/v2",
                                 json={"query": query}, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for edge in data.get("data", {}).get("projects", {}).get("edges", []):
                    node = edge.get("node", {})
                    resources.append({
                        "id": f"railway:{node.get('id', '')}",
                        "label": node.get("name", "Unknown"),
                    })

        elif provider.name == "twilio":
            sid = creds.get("account_sid", "")
            auth = creds.get("auth_token", "")
            # List common categories
            for cat in ["sms", "calls", "phonenumbers", "recordings", "totalprice"]:
                resources.append({"id": f"twilio:{cat}", "label": f"Twilio: {cat}"})

        elif provider.name == "cloudflare":
            api_token = creds.get("api_token", "")
            account_id = creds.get("account_id", "")
            headers = {"Authorization": f"Bearer {api_token}"}
            resp = requests.get(
                f"https://api.cloudflare.com/client/v4/zones?account.id={account_id}&per_page=50",
                headers=headers, timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            for zone in data.get("result", []):
                resources.append({
                    "id": f"cloudflare-zone:{zone['id']}",
                    "label": zone["name"],
                })

    except Exception as e:
        current_app.logger.error(f"Error listing resources for {provider.name}: {e}")

    return resources


# ── Dashboard Data ──────────────────────────────────────────


def get_cost_summary(months=6):
    now = date.today()
    start = (now.replace(day=1) - timedelta(days=months * 30)).replace(day=1)

    entries = ServiceCostEntry.query.filter(
        ServiceCostEntry.period_start >= start,
    ).all()

    by_provider = {}
    by_client = {}
    by_month = {}
    unallocated = 0
    total = 0

    for e in entries:
        total += e.allocated_amount

        # By provider
        pname = e.provider.display_name if e.provider else "Unknown"
        by_provider[pname] = by_provider.get(pname, 0) + e.allocated_amount

        # By client
        if e.mapping and e.mapping.client:
            cname = e.mapping.client.name
            by_client[cname] = by_client.get(cname, 0) + e.allocated_amount
        else:
            unallocated += e.allocated_amount

        # By month
        month_key = e.period_start.strftime("%Y-%m")
        by_month[month_key] = by_month.get(month_key, 0) + e.allocated_amount

    return {
        "total": round(total, 2),
        "unallocated": round(unallocated, 2),
        "by_provider": {k: round(v, 2) for k, v in sorted(by_provider.items())},
        "by_client": {k: round(v, 2) for k, v in sorted(by_client.items(), key=lambda x: -x[1])},
        "by_month": {k: round(v, 2) for k, v in sorted(by_month.items())},
    }
