"""Build the leads list for the Paris, Texas trade area out of public records.

Re-runnable. Every business gets a `dedupe_key` made of its trading name and
its street, so a second run updates rather than duplicates, and a source that
arrives later only fills the gaps an earlier one left. Nothing typed by hand
on the board is ever overwritten: the stage, the notes, the people added by
somebody and the employee and revenue figures are left exactly as found.

The sources, all free, all public:

  Texas Comptroller, Active Sales Tax Permit Holders (jrea-zgmq)
      Every business permitted to sell anything taxable. Trading name, street,
      industry code, the date it started selling, and the legal entity behind
      it. This is the spine of the list.
  Texas Comptroller, Active Franchise Taxpayers (9cir-efmm)
      The registered entities. This one ENRICHES and never creates: a
      registration proves a company exists, not that it trades or wants
      customers, and the file is full of holding entities, dormant shells and
      single-property LLCs. It supplies the legal name, the entity type and
      the charter date for a business some other source already found.
  Overture Maps places (open data, read with DuckDB over S3)
      The one source that carries contact details at scale: phone numbers,
      emails, websites and social pages for four thousand places in this
      trade area. Optional - if DuckDB or the network is missing the import
      says so and carries on without it.
  OpenStreetMap, via Overpass
      Where a place is, and occasionally how to reach it.
  CMS National Provider Identifier registry
      Every healthcare provider, with a phone and the name of the authorised
      official, who at a clinic this size is usually the owner. Individual
      providers become named contacts at the practice they work from.
  FMCSA motor carrier census (data.transportation.gov, az4n-8mr2)
      Every business with a US DOT number: a telephone number, and the only
      headcount in any of this, because a carrier files its driver count.
      Rural Texas runs on trucks, so this is a big slice of the area.
  Texas Department of Licensing and Regulation, all licences (7358-krk7)
      The salons, the air conditioning and electrical contractors, the tow
      companies: BUSINESS licences only, with the owner named. The same file
      lists every cosmetology operator and apprentice electrician in the
      county and those are employees at somebody else's shop, not businesses;
      counting them was how one list grew by two thousand names that could
      not be rung.
  The businesses' own websites
      Fetched once each, homepage and contact page, for a published email.

What deliberately stays mostly empty: employee counts and revenue. The only
headcount in the public record is a haulier's driver count, which is filed
with the FMCSA and is carried here as-is; nothing else publishes a headcount
or a turnover for a private firm in a town of 25,000, and a guessed figure on
a call sheet is worse than a blank one. What the record does give
is a better signal anyway: how long they have traded, how many locations they
run, and whether they have a website at all.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

UA = {"User-Agent": "BuiltByBean-Leads/1.0 (michael@builtbybean.com)"}

# Comptroller county codes: Lamar, Red River, Delta, Fannin.
COUNTIES = {"139": "Lamar", "194": "Red River", "060": "Delta", "074": "Fannin"}

# Lamar is Paris and its towns, Red River and Delta are half an hour out.
# Fannin is only in the list for its eastern edge: Bonham is forty miles from
# Paris and Whitewright sixty, which is Sherman's trade area, not this one.
HOME_COUNTIES = ("139", "194", "060")
NEAR_FANNIN = {"HONEY GROVE", "WINDOM", "LADONIA", "DODD CITY", "ECTOR",
               "TELEPHONE", "RAVENNA", "IVANHOE", "BAILEY"}


def in_orbit(city, county_code):
    """Close enough to Paris to be worth the drive."""
    if county_code in HOME_COUNTIES:
        return True
    return str(city or "").strip().upper() in NEAR_FANNIN


# A licence held by a PERSON is a qualification; a licence held by a BUSINESS
# is a business. Only these are the second kind. Everything else in that file
# is somebody's employee.
BUSINESS_LICENCES = {
    "Full Service Establishment", "Mini Establishment",
    "Manicurist/Esthetician Establishment", "Barber Shop", "Dual Shop/Salon",
    "Cosmetology Private School", "Barber School", "Booth Rental",
    "A/C Contractor", "Electrical Contractor", "Sign Electrical Contractor",
    "Elevator Contractor", "Water Well Driller", "Auctioneer",
    "Licensed Breeder", "Vehicle Storage Facility", "Tow Company",
    "Used Automotive Parts Recycler", "Air Conditioning Contractor",
}

# Paris sits at 33.66 / -95.55. The box reaches Bonham in the west and
# Clarksville in the east.
BBOX = (33.10, -96.30, 34.05, -94.90)

# Tighter, for Overture: the orbit only, west to east.
ORBIT_BOX = (-96.15, 33.25, -94.85, 33.98)

# Overture knows about lakes and picnic areas as well as businesses. These
# categories are places, not somebody to ring.
# The marks this file writes. Anything else on a row was put there by a
# later pass and is not the import's to remove.
KNOWN_SOURCES = {"comptroller", "franchise", "openstreetmap", "overture",
                 "npi", "fmcsa", "tdlr"}

NOT_A_TRADER = {
    "park", "lake", "river", "stream", "forest", "trail", "beach", "island",
    "mountain", "dam", "bridge", "monument", "landmark_and_historical_building",
    "cemetery", "playground", "picnic_area", "rest_area", "scenic_point",
    "bus_stop", "parking", "parking_lot", "atm", "post_office",
    "fire_department", "police_department", "public_restroom", "campground",
    "hiking_trail", "fishing", "boat_ramp", "airport_terminal", "harbor",
    "historical_landmark", "tourist_information", "water_tower",
}

NPI_CITIES = [
    "Paris", "Blossom", "Reno", "Powderly", "Sumner", "Brookston", "Deport",
    "Roxton", "Pattonville", "Arthur City", "Petty", "Toco", "Chicota",
    "Clarksville", "Bogata", "Avery", "Detroit", "Annona", "Bagwell",
    "Cooper", "Klondike", "Pecan Gap", "Ben Franklin",
    "Honey Grove", "Ladonia", "Windom", "Dodd City", "Ector", "Telephone",
    "Ravenna", "Ivanhoe", "Bailey",
]

# Towns the orbit excludes on purpose. Named, so that a mistyped city can
# never be one of them, and checked even when the postcode looks local:
# Commerce sits on the Delta county line and its postcode is in the trade
# area, which let ninety Hunt County businesses in behind it.
FAR_TOWNS = {
    "BONHAM", "LEONARD", "TRENTON", "SAVOY", "WHITEWRIGHT", "WOLFE CITY",
    "BLUE RIDGE", "RANDOLPH", "GOBER", "COMMERCE", "CELESTE", "CAMPBELL",
    "GREENVILLE", "SULPHUR SPRINGS", "MOUNT PLEASANT", "CUMBY", "DE KALB",
    "CUNNINGHAM", "HUGO", "WINFIELD",
}

# NAICS, most specific first. Sector names are the official ones; the
# subsector names are the plain-English half of them, because "2382" on a
# call sheet is not a trade and "Building equipment contractors" is.
NAICS_4 = {
    "2361": "Home builders", "2362": "Commercial builders",
    "2371": "Utility line contractors", "2381": "Building trade contractors",
    "2382": "Plumbing, heating and electrical", "2383": "Painting and finishing",
    "2389": "Site preparation and other trades",
    "4411": "Car and truck dealers", "4413": "Auto parts and tyres",
    "4441": "Building materials", "4442": "Lawn and garden",
    "4451": "Grocery stores", "4453": "Beer, wine and liquor",
    "4461": "Pharmacy and personal care", "4471": "Filling stations",
    "4481": "Clothing", "4482": "Shoes", "4483": "Jewellery",
    "4511": "Sporting goods and hobby", "4512": "Books and music",
    "4522": "Department stores", "4523": "General merchandise",
    "4531": "Florists", "4532": "Office supplies and gifts",
    "4533": "Used goods", "4539": "Other retail",
    "4841": "Trucking", "4842": "Specialised freight",
    "5221": "Banks and credit unions", "5222": "Lenders",
    "5231": "Investment brokers", "5241": "Insurance carriers",
    "5242": "Insurance agents", "5311": "Landlords",
    "5312": "Estate agents", "5321": "Vehicle hire", "5324": "Equipment hire",
    "5411": "Solicitors", "5412": "Accountants and bookkeepers",
    "5413": "Architects, engineers and surveyors", "5414": "Design services",
    "5415": "Computer services", "5416": "Consultants",
    "5417": "Research", "5418": "Advertising and marketing",
    "5419": "Other professional services",
    "5611": "Office administration", "5613": "Employment agencies",
    "5617": "Cleaning and landscaping", "5621": "Waste collection",
    "6111": "Schools", "6113": "Colleges", "6116": "Tutors and instructors",
    "6211": "Doctors", "6212": "Dentists", "6213": "Other practitioners",
    "6214": "Clinics", "6216": "Home health care", "6221": "Hospitals",
    "6231": "Nursing homes", "6233": "Assisted living", "6244": "Child care",
    "7111": "Performing arts", "7139": "Recreation",
    "7211": "Hotels and motels", "7223": "Caterers",
    "7224": "Bars", "7225": "Restaurants and cafes",
    "8111": "Car repair", "8112": "Electronics repair",
    "8113": "Machinery repair", "8114": "Household goods repair",
    "8121": "Salons and barbers", "8122": "Funeral homes",
    "8123": "Dry cleaners and laundries", "8129": "Other personal services",
    "8131": "Churches", "8134": "Civic organisations",
    "8139": "Trade and professional bodies", "8141": "Private households",
}
NAICS_3 = {
    "236": "Building construction", "237": "Heavy construction",
    "238": "Building trade contractors", "441": "Vehicle dealers",
    "444": "Building and garden supplies", "445": "Food and drink shops",
    "446": "Pharmacy and personal care", "447": "Filling stations",
    "448": "Clothing and accessories", "451": "Sport, hobby and books",
    "452": "General merchandise", "453": "Other retail",
    "454": "Direct and online sellers", "484": "Trucking",
    "492": "Couriers", "517": "Telecoms", "522": "Banks and lenders",
    "523": "Investments", "524": "Insurance", "531": "Property",
    "532": "Hire and leasing", "541": "Professional services",
    "561": "Business support", "562": "Waste services",
    "611": "Education", "621": "Health practices", "622": "Hospitals",
    "623": "Care homes", "624": "Social services",
    "711": "Performing arts", "713": "Recreation", "721": "Accommodation",
    "722": "Restaurants and bars", "811": "Repair shops",
    "812": "Personal services", "813": "Churches and associations",
}
NAICS_2 = {
    "11": "Farming and forestry", "21": "Mining and drilling", "22": "Utilities",
    "23": "Construction", "31": "Manufacturing", "32": "Manufacturing",
    "33": "Manufacturing", "42": "Wholesale", "44": "Retail", "45": "Retail",
    "48": "Transport", "49": "Transport and warehousing", "51": "Media and telecoms",
    "52": "Finance and insurance", "53": "Property and leasing",
    "54": "Professional services", "55": "Holding companies",
    "56": "Business and waste services", "61": "Education",
    "62": "Health and social care", "71": "Arts and recreation",
    "72": "Hotels and restaurants", "81": "Other services",
    "92": "Public bodies",
}

# What the Comptroller's organisation-type letters mean. The ones that
# matter here are the sole traders, because for those the taxpayer name is
# the owner's name.
ENTITY_TYPES = {
    "CF": "Foreign corporation", "CI": "Texas corporation", "CM": "Foreign corporation",
    "CN": "Texas corporation", "CP": "Texas corporation", "CR": "Texas corporation",
    "CS": "Texas corporation", "CT": "Texas corporation", "CU": "Texas corporation",
    "AB": "Business association", "AC": "Business association", "AF": "Business association",
    "AP": "Business association", "AR": "Business association",
    "PF": "Limited partnership", "PI": "Partnership", "PL": "Limited partnership",
    "PV": "Limited partnership", "PW": "Partnership", "PX": "Partnership",
    "SL": "Sole owner", "SO": "Sole owner", "IN": "Sole owner",
    "TF": "Trust", "TH": "Trust", "TI": "Trust", "TR": "Trust",
    "FA": "Family entity", "HF": "Holding company", "ES": "Estate",
    "GO": "Government", "PA": "Professional association",
    "CB": "Professional corporation", "CD": "Professional corporation",
    "CE": "Professional corporation",
}
SOLE_OWNER_TYPES = {"SL", "SO", "IN"}

# Words that stay upper case when a shouted name is made readable.
KEEP_UPPER = {
    "LLC", "L.L.C.", "INC", "LLP", "LP", "LTD", "PC", "PA", "PLLC", "USA", "US",
    "TX", "BBQ", "AC", "HVAC", "TV", "ATM", "RV", "II", "III", "IV", "DBA",
    "CPA", "DDS", "MD", "AT&T", "H&R", "J&J", "B&B", "&",
}
LOWER_WORDS = {"and", "of", "the", "at", "on", "in", "for", "de", "la", "by"}

# Entities that exist on paper and answer no telephone. A cemetery
# association is not a business with a marketing budget, and a family trust
# is a legal wrapper around a field.
NOT_A_BUSINESS = [
    re.compile(r"\bcemet", re.I),
    re.compile(r"(family|living|revocable|irrevocable)\s+trust\b", re.I),
    re.compile(r"\btrust\s*$", re.I),
    re.compile(r"^estate of\b", re.I),
    re.compile(r"parent\s*[-/]?\s*teacher", re.I),
    re.compile(r"booster\s+club", re.I),
    re.compile(r"scholarship\s+(fund|foundation)", re.I),
    re.compile(r"(home\s*owners|property\s+owners)[''’]?s?\s+assoc", re.I),
]
PAPER_ONLY_TYPES = {"Trust", "Estate", "Family entity"}


def trades_here(entry, towns, zips):
    """Is this a business, in the trade area, that could be rung.

    The postcode is asked first and settles it on its own, because a postcode
    is filed by machine and a town name is typed by a person: one permit in
    this dataset has AUSTIN in the town field and 75452, which is Leonard, in
    the postcode. Trusting the town name put six thousand Austin haulage
    firms into a Paris call list.

    Then the ways to fail. Not a business at all. Registered in one of these
    counties but posting to a head office in Charlotte or Frisco, which is a
    filing address rather than a front door. Or a map feature with no town, no
    postcode, no phone and no website, which is a chapel the map happened to
    name and nothing anybody can contact.
    """
    name = entry.get("name") or ""
    if any(bad.search(name) for bad in NOT_A_BUSINESS):
        return False
    if entry.get("entity_type") in PAPER_ONLY_TYPES:
        return False
    city = (entry.get("city") or "").strip()
    if city.upper() in FAR_TOWNS:
        return False
    postcode = (entry.get("zip_code") or "").strip()[:5]
    if postcode:
        return postcode in zips
    if city:
        return city.lower() in towns
    # A licence is pulled by county, so its county is proof enough of where
    # it is even when nothing else is filed with it.
    if entry.get("county"):
        return True
    return bool(entry.get("phone") or entry.get("website") or entry.get("email"))


# The Comptroller files "we do not know" as the day the sales tax began.
# A business is not 65 years old because nobody wrote down when it started.
SALES_TAX_EPOCH = "1961-09-01"

# One vocabulary for the trade. A map, a licence file and an industry code
# name the same shop three ways, and three options in a filter that each hide
# the other two is worse than one long list. The NAICS wording wins because
# most rows come from there; anything not in here keeps its own words.
TRADE_ALIASES = {
    "restaurant": "Restaurants and cafes",
    "fast food": "Restaurants and cafes",
    "cafe": "Restaurants and cafes",
    "food court": "Restaurants and cafes",
    "ice cream": "Restaurants and cafes",
    "restaurants and bars": "Restaurants and cafes",
    "bar": "Bars", "pub": "Bars", "biergarten": "Bars",
    "convenience": "Filling stations", "fuel": "Filling stations",
    "supermarket": "Grocery stores", "greengrocer": "Grocery stores",
    "butcher": "Grocery stores", "bakery": "Grocery stores",
    "car repair": "Car repair", "car parts": "Auto parts and tyres",
    "tyres": "Auto parts and tyres", "tires": "Auto parts and tyres",
    "car": "Car and truck dealers", "car dealer": "Car and truck dealers",
    "bank": "Banks and credit unions", "atm": "Banks and credit unions",
    "money lender": "Lenders", "insurance": "Insurance agents",
    "dentist": "Dentists", "doctors": "Doctors", "clinic": "Clinics",
    "optometrist": "Other practitioners", "pharmacy": "Pharmacy and personal care",
    "chemist": "Pharmacy and personal care", "veterinary": "Other practitioners",
    "hairdresser": "Salons and barbers", "beauty": "Salons and barbers",
    "barber": "Salons and barbers", "full service establishment": "Salons and barbers",
    "mini establishment": "Salons and barbers",
    "manicurist/esthetician establishment": "Salons and barbers",
    "hardware": "Building materials", "doityourself": "Building materials",
    "trade": "Building materials", "garden centre": "Lawn and garden",
    "florist": "Florists", "funeral directors": "Funeral homes",
    "laundry": "Dry cleaners and laundries", "dry cleaning": "Dry cleaners and laundries",
    "a/c contractor": "Plumbing, heating and electrical",
    "air conditioning contractor": "Plumbing, heating and electrical",
    "electrical contractor": "Plumbing, heating and electrical",
    "sign electrical contractor": "Plumbing, heating and electrical",
    "plumber": "Plumbing, heating and electrical",
    "electrician": "Plumbing, heating and electrical",
    "hvac": "Plumbing, heating and electrical",
    "place of worship": "Churches", "school": "Schools",
    "kindergarten": "Child care", "childcare": "Child care",
    "clothes": "Clothing", "shoes": "Shoes", "jewelry": "Jewellery",
    "hotel": "Hotels and motels", "motel": "Hotels and motels",
    "fitness centre": "Recreation", "sports centre": "Recreation",
    "auctioneer": "Auctioneers", "licensed breeder": "Farming and forestry",
    "vehicle storage facility": "Car repair", "tow company": "Trucking",
    "water well driller": "Site preparation and other trades",
    "elevator contractor": "Building trade contractors",
    "used automotive parts recycler": "Auto parts and tyres",
    "cosmetology private school": "Schools", "barber school": "Schools",
    "booth rental": "Salons and barbers", "dual shop/salon": "Salons and barbers",
    "barber shop": "Salons and barbers",
}


# Overture's second-level categories, folded into the words the tax roll
# already uses. A place keeps the trade its industry code would have given
# it, whichever file found it first.
OVERTURE_TRADES = {
    "agricultural_service": "Farming and forestry",
    "air_transport_facility_or_service": "Transport",
    "alcoholic_beverage_venue": "Bars",
    "amusement_attraction": "Recreation",
    "animal_attraction": "Recreation",
    "animal_or_pet_service": "Pet services",
    "arts_and_crafts_space": "Arts and recreation",
    "arts_and_entertainment": "Arts and recreation",
    "b2b_service": "Business services",
    "bed_and_breakfast": "Hotels and motels",
    "building_or_construction_service": "Building trade contractors",
    "campground": "Campsites and RV parks",
    "casual_eatery": "Restaurants and cafes",
    "civic_organization": "Churches and associations",
    "community_and_government": "Public bodies",
    "convenience_store": "Filling stations",
    "corporate_or_business_office": "Business services",
    "department_store": "General merchandise",
    "design_service": "Design services",
    "discount_store": "General merchandise",
    "education": "Schools", "educational_service": "Schools",
    "emergency_or_urgent_care_facility": "Clinics",
    "environmental_or_ecological_service": "Waste services",
    "event_or_party_service": "Events and catering",
    "event_venue": "Events and catering",
    "family_service": "Social services",
    "fashion_and_apparel_store": "Clothing",
    "festival_venue": "Events and catering",
    "financial_service": "Finance and insurance",
    "food_and_beverage_store": "Grocery stores",
    "food_and_drink": "Restaurants and cafes",
    "food_service": "Restaurants and cafes",
    "fueling_station": "Filling stations",
    "gaming_venue": "Recreation",
    "government_office": "Public bodies",
    "ground_transport_facility_or_service": "Transport",
    "health_care": "Health practices",
    "historic_site": "Arts and recreation",
    "home_service": "Home services",
    "hospital": "Hospitals",
    "hotel": "Hotels and motels", "inn": "Hotels and motels",
    "lodge": "Hotels and motels", "lodging": "Hotels and motels",
    "private_lodging": "Hotels and motels", "resort": "Hotels and motels",
    "housing_or_property_service": "Property",
    "industrial_facility_or_service": "Manufacturing",
    "laundry_service": "Dry cleaners and laundries",
    "legal_service": "Solicitors",
    "library": "Schools",
    "market": "Grocery stores",
    "media_service": "Advertising and marketing",
    "medical_service": "Health practices",
    "movie_theater": "Arts and recreation",
    "museum": "Arts and recreation",
    "nightlife_venue": "Bars",
    "non_alcoholic_beverage_venue": "Restaurants and cafes",
    "outpatient_care_facility": "Health practices",
    "performing_arts_venue": "Arts and recreation",
    "personal_or_beauty_service": "Salons and barbers",
    "place_of_learning": "Schools",
    "place_of_worship": "Churches",
    "printing_service": "Printing and signs",
    "professional_service": "Professional services",
    "public_facility": "Public bodies",
    "public_safety_service": "Public bodies",
    "public_utility": "Utilities",
    "real_estate_service": "Property",
    "religious_organization": "Churches",
    "rental_service": "Hire and leasing",
    "restaurant": "Restaurants and cafes",
    "rv_park": "Campsites and RV parks",
    "second_hand_store": "Other retail",
    "shipping_or_delivery_service": "Couriers",
    "shopping": "Other retail",
    "shopping_mall": "Other retail",
    "social_or_community_service": "Social services",
    "specialized_medical_facility": "Health practices",
    "specialty_store": "Other retail",
    "sport_or_fitness_facility": "Recreation",
    "sport_or_recreation_club": "Recreation",
    "sports_and_recreation": "Recreation",
    "stadium_arena": "Recreation",
    "storage_facility": "Storage",
    "technical_service": "Computer services",
    "telecommunications_service": "Telecoms",
    "travel_and_transportation": "Transport",
    "travel_service": "Travel agents",
    "vehicle_dealer": "Car and truck dealers",
    "vehicle_service": "Car repair",
    "warehouse_club_store": "General merchandise",
    "wellness_service": "Health practices",
}

# Places that are not businesses even at the group level.
NOT_A_TRADE_GROUP = {
    "park", "water_feature", "land_feature", "built_feature",
    "geographic_entities", "recreational_trail_or_path", "memorial_site",
    "military_site", "rural_attraction",
}


def overture_trade(hierarchy):
    """The group a place belongs to, in the words the rest of the list uses.

    Overture's leaf is too fine for a call sheet: Academic bookstore and
    Antique store are both somewhere to ring about a website, and 587
    options is a filter nobody opens twice.
    """
    levels = [str(x) for x in (hierarchy or []) if x]
    if not levels:
        return ""
    group = levels[1] if len(levels) > 1 else levels[0]
    if group in NOT_A_TRADE_GROUP:
        return ""
    known = OVERTURE_TRADES.get(group)
    if known:
        return known
    return group.replace("_", " ").capitalize()


def trade(label):
    """One name per trade, whichever source named it."""
    text = re.sub(r"\s+", " ", (label or "").strip())
    if not text:
        return ""
    return TRADE_ALIASES.get(text.lower(), text)


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BAD_EMAIL = re.compile(r"(sentry|wixpress|example|\.png$|\.jpg$|\.gif$|\.webp$|@2x|domain\.com|email\.com|yourdomain)", re.I)


# ── the plumbing ────────────────────────────────────────────

def fetch(url, data=None, timeout=120, tries=3):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA, data=data)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:
            last = exc
            if attempt < tries - 1:
                time.sleep(4 * (attempt + 1))
    raise last


def socrata(dataset, where, order, page=50000):
    rows, offset = [], 0
    while True:
        url = f"https://data.texas.gov/resource/{dataset}.json?" + urllib.parse.urlencode(
            {"$where": where, "$limit": page, "$offset": offset, "$order": order})
        batch = json.loads(fetch(url))
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


def pretty(text):
    """A shouted public-record name, made readable."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    if text != text.upper():
        return text
    out = []
    for word in text.split(" "):
        bare = word.strip(".,")
        if bare in KEEP_UPPER or (len(bare) <= 3 and bare.isupper() and any(c in bare for c in "&.")):
            out.append(word)
        elif word.lower() in LOWER_WORDS and out:
            out.append(word.lower())
        else:
            out.append(word.capitalize())
    joined = " ".join(out)
    # An apostrophe should not start a new word: BOB'S becomes Bob's.
    return re.sub(r"'(\w)", lambda m: "'" + m.group(1).lower(), joined)


def town(name):
    """One spelling per town. pretty() leaves already-mixed text alone, so a
    source that files "paris" in lower case would sit beside "Paris" as a
    second town in the filter."""
    text = pretty(name)
    return text.title() if text and (text.islower() or text.isupper()) else text


def norm(text):
    """Flattened for matching: letters and digits only.

    "and" goes with the ampersand it stands for. Dropping punctuation alone
    left Paris Jewelry & Loan and Paris Jewelry and Loan as two businesses.
    """
    text = (text or "").lower().replace("&", " and ")
    text = re.sub(r"\b(llc|inc|l l c|ltd|lp|llp|pllc|pc|co|company|corp|the|and)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def street_key(address):
    """The house number and the first word of the street, which is enough to
    tell two shops apart and forgiving enough to match ST against STREET."""
    parts = re.sub(r"[^A-Za-z0-9 ]", " ", (address or "").lower()).split()
    return "".join(parts[:2])


def naics_label(code):
    code = (code or "").strip()
    for table, width in ((NAICS_4, 4), (NAICS_3, 3), (NAICS_2, 2)):
        if len(code) >= width and code[:width] in table:
            return table[code[:width]]
    return ""


def owner_from_taxpayer(name, org_type):
    """A sole trader's taxpayer name is the owner, filed surname first."""
    if org_type not in SOLE_OWNER_TYPES:
        return ""
    bare = re.sub(r"\s+(DBA|D/B/A)\s+.*$", "", (name or "").strip(), flags=re.I)
    parts = [p for p in bare.split() if p]
    if len(parts) < 2 or len(parts) > 4:
        return ""
    return pretty(" ".join(parts[1:] + [parts[0]]))


def parse_date(value):
    if not value:
        return None
    # The epoch is a filing convention for "unknown", not a date.
    if str(value)[:10] == SALES_TAX_EPOCH:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except Exception:
        return None


def digits(phone):
    return re.sub(r"\D", "", phone or "")


def tidy_phone(phone):
    d = digits(phone)
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d if len(d) == 10 else ""


def tidy_site(url):
    url = (url or "").strip()
    if not url or url.startswith(("mailto:", "tel:")):
        return ""
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    return url[:300]


# ── the sources ─────────────────────────────────────────────

def load(cache, name, build):
    """Read the cached pull if there is one, otherwise go and get it."""
    if cache:
        path = os.path.join(cache, f"raw_{name}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                rows = json.load(handle)
            print(f"  {name}: {len(rows)} from cache")
            return rows
    rows = build()
    print(f"  {name}: {len(rows)} fetched")
    if cache:
        with open(os.path.join(cache, f"raw_{name}.json"), "w", encoding="utf-8") as handle:
            json.dump(rows, handle)
    return rows


def get_permits(cache):
    codes = ",".join(f"'{c}'" for c in COUNTIES)
    return load(cache, "permits", lambda: socrata(
        "jrea-zgmq", f"outlet_county_code in({codes})", "taxpayer_number"))


def get_franchise(cache):
    codes = ",".join(f"'{c}'" for c in COUNTIES)
    return load(cache, "franchise", lambda: socrata(
        "9cir-efmm", f"taxpayer_county_code in({codes})", "taxpayer_number"))


def get_osm(cache):
    south, west, north, east = BBOX
    area = f"{south},{west},{north},{east}"
    keys = ["shop", "office", "amenity", "craft", "healthcare", "tourism",
            "leisure", "industrial"]
    body = "".join(f'node["name"]["{k}"]({area});way["name"]["{k}"]({area});' for k in keys)
    query = f"[out:json][timeout:600];({body});out center tags;"

    def build():
        for host in ("https://overpass-api.de/api/interpreter",
                     "https://overpass.kumi.systems/api/interpreter"):
            try:
                data = urllib.parse.urlencode({"data": query}).encode()
                return json.loads(fetch(host, data=data, timeout=600, tries=2)).get("elements", [])
            except Exception as exc:
                print(f"    {host}: {str(exc)[:80]}")
        return []

    return load(cache, "osm", build)


def get_npi(cache):
    def build():
        seen, rows = set(), []
        for city in NPI_CITIES:
            for skip in range(0, 1200, 200):
                url = "https://npiregistry.cms.hhs.gov/api/?" + urllib.parse.urlencode(
                    {"version": "2.1", "city": city, "state": "TX", "limit": 200, "skip": skip})
                try:
                    batch = json.loads(fetch(url, timeout=90)).get("results", [])
                except Exception:
                    break
                fresh = [r for r in batch if r.get("number") not in seen]
                seen.update(r.get("number") for r in fresh)
                rows.extend(fresh)
                if len(batch) < 200:
                    break
            time.sleep(0.2)
        return rows

    return load(cache, "npi", build)


def statewide_locations(taxpayer_numbers):
    """How many outlets each taxpayer runs in the whole state.

    One shop or nine is a size signal nobody had to publish, and it is the
    closest thing to a headcount the public record offers. Asked in batches,
    because three thousand separate questions would be rude.
    """
    counts, batch = {}, 200
    numbers = sorted(n for n in taxpayer_numbers if n)
    for start in range(0, len(numbers), batch):
        chunk = numbers[start:start + batch]
        where = "taxpayer_number in(" + ",".join(f"'{n}'" for n in chunk) + ")"
        try:
            rows = json.loads(fetch(
                "https://data.texas.gov/resource/jrea-zgmq.json?" + urllib.parse.urlencode(
                    {"$select": "taxpayer_number, count(1)", "$group": "taxpayer_number",
                     "$where": where, "$limit": batch})))
            for row in rows:
                counts[row["taxpayer_number"]] = int(row.get("count_1") or 1)
        except Exception as exc:
            print(f"    locations batch {start}: {str(exc)[:70]}")
    return counts


def get_carriers(cache, towns_upper):
    """Anyone with a US DOT number and a front door in the trade area."""
    inlist = ",".join(f"'{t}'" for t in sorted(towns_upper))
    where = f"phy_state='TX' AND phy_city in({inlist})"

    def build():
        rows, offset = [], 0
        while True:
            url = "https://data.transportation.gov/resource/az4n-8mr2.json?" + urllib.parse.urlencode(
                {"$where": where, "$limit": 20000, "$offset": offset, "$order": "dot_number"})
            batch = json.loads(fetch(url, timeout=240))
            rows.extend(batch)
            if len(batch) < 20000:
                return rows
            offset += 20000

    return load(cache, "carriers", build)


def get_overture(cache):
    """Places for the orbit, read straight off Overture's public parquet.

    DuckDB is an optional dependency. If it or the network is not there the
    import says so and goes on: everything else still works, there are just
    fewer telephone numbers.
    """
    cached = os.path.join(cache, "raw_overture.json") if cache else None
    if cached and os.path.exists(cached):
        with open(cached, encoding="utf-8") as handle:
            rows = json.load(handle)
        print(f"  overture: {len(rows)} from cache")
        return rows
    try:
        import duckdb
    except ImportError:
        print("  overture: duckdb is not installed, skipping (pip install duckdb)")
        return []
    try:
        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
        release = _overture_release()
        if not release:
            print("  overture: no release found, skipping")
            return []
        w, s_, e, n = ORBIT_BOX
        src = f"s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
        got = con.execute(f"""
            SELECT id, names.primary AS name, categories.primary AS category,
                   taxonomy.hierarchy AS hierarchy,
                   confidence, phones, websites, emails, socials, addresses,
                   bbox.xmin AS lon, bbox.ymin AS lat
            FROM read_parquet('{src}', hive_partitioning=1)
            WHERE bbox.xmin BETWEEN {w} AND {e} AND bbox.ymin BETWEEN {s_} AND {n}
        """).fetchall()
        cols = [d[0] for d in con.description]
    except Exception as exc:
        print(f"  overture: {str(exc)[:120]}, skipping")
        return []

    rows = []
    for raw in got:
        row = dict(zip(cols, raw))
        for key in ("phones", "websites", "emails", "socials", "hierarchy"):
            row[key] = list(row.get(key) or [])
        addr = row.get("addresses")
        row["addresses"] = dict(addr) if hasattr(addr, "keys") else None
        rows.append(row)
    print(f"  overture: {len(rows)} fetched")
    if cached:
        with open(cached, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, default=str)
    return rows


def _overture_release():
    """The newest release in the public bucket."""
    try:
        url = ("https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/"
               "?list-type=2&delimiter=/&prefix=release/")
        xml = fetch(url, timeout=90).decode()
        found = sorted(set(re.findall(r"<Prefix>release/([^<]+)/</Prefix>", xml)))
        return found[-1] if found else ""
    except Exception:
        return ""


def get_licences(cache):
    # Home counties only: a Fannin licence is almost always a Bonham one.
    counties = ",".join(f"'{COUNTIES[c].upper()}'" for c in HOME_COUNTIES)
    return load(cache, "licences_home", lambda: socrata(
        "7358-krk7", f"business_county in({counties})", "license_number"))


def get_salons(cache):
    """The one state licence file that carries a telephone number."""
    return load(cache, "salons", lambda: socrata(
        "9d9z-ebct", "mailing_address_city_state_zip is not null", "license_number"))


def person_name(filed):
    """A licence files a person as SURNAME, FIRST MIDDLE."""
    text = (filed or "").strip()
    if "," not in text:
        return ""
    last, _, rest = text.partition(",")
    rest = rest.strip()
    if not rest or not last.strip():
        return ""
    return pretty(f"{rest} {last.strip()}")


def scrape_email(site):
    """One business's own website, asked once for a published address."""
    found = []
    for path in ("", "/contact", "/contact-us", "/about"):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(site.rstrip("/") + path, headers=UA), timeout=10) as r:
                if r.status != 200:
                    continue
                html = r.read(400000).decode("utf-8", "ignore")
        except Exception:
            continue
        for match in EMAIL_RE.findall(html):
            if not BAD_EMAIL.search(match) and len(match) < 90:
                found.append(match.lower())
        if found:
            break
    if not found:
        return ""
    # Prefer an address at the business's own domain over a free mailbox.
    host = urllib.parse.urlparse(site).netloc.replace("www.", "").lower()
    for candidate in found:
        if host and host.split(".")[0] in candidate.split("@")[-1]:
            return candidate
    return found[0]


# ── the build ───────────────────────────────────────────────

def _merge_duplicates(db, Lead, LeadPerson):
    """One row per business per town. See the note on norm()."""
    groups = {}
    for lead in Lead.query.all():
        key = (norm(lead.name), (lead.city or "").strip().lower())
        if key[0]:
            groups.setdefault(key, []).append(lead)

    # Everything a person might have put on a row. A row carrying any of it
    # is never the one that gets deleted, and never deleted at all.
    def worked(lead):
        return bool(lead.touches or (lead.notes or "").strip() or lead.client_id
                    or any(p.source == "typed" for p in lead.people))

    def richness(lead):
        return sum(1 for f in ("phone", "email", "website", "owner_name", "social",
                               "address", "industry", "started_on", "employees")
                   if getattr(lead, f))

    removed = 0
    for rows in groups.values():
        if len(rows) < 2:
            continue
        keep = max(rows, key=lambda l: (worked(l), richness(l), -l.id))
        for other in rows:
            if other is keep or worked(other):
                continue
            for field in ("phone", "email", "website", "social", "owner_name",
                          "legal_name", "address", "zip_code", "county", "industry",
                          "naics", "entity_type", "started_on", "employees",
                          "revenue", "lat", "lon", "taxpayer_number", "osm_ref",
                          "overture_id", "npi", "website_checked_at"):
                if not getattr(keep, field) and getattr(other, field):
                    setattr(keep, field, getattr(other, field))
            marks = [m for m in (keep.sources or "").split(",") if m]
            for mark in (other.sources or "").split(","):
                if mark and mark not in marks:
                    marks.append(mark)
            keep.sources = ",".join(marks)[:200]
            have = {(p.name or "").lower() for p in keep.people}
            for person in list(other.people):
                if (person.name or "").lower() in have:
                    continue
                have.add((person.name or "").lower())
                person.lead_id = keep.id
            db.session.delete(other)
            removed += 1
    if removed:
        db.session.commit()
    return removed


def run(cache=None, enrich=True, verbose=True):
    from app import create_app
    from models import db, Lead, LeadPerson

    app = create_app()
    with app.app_context():
        print("Reading the public record...")
        permits = get_permits(cache)
        franchise = get_franchise(cache)
        osm = get_osm(cache)
        npi = get_npi(cache)

        # The trade area as the state draws it rather than as a rectangle
        # does: every postcode somebody holds a sales tax permit in, and every
        # town that holds more than one of them. More than one, because a
        # town appearing exactly once is as likely to be a typing mistake as
        # a hamlet, and the postcode covers the real hamlets anyway.
        permits = [p for p in permits
                   if in_orbit(p.get("outlet_city"), str(p.get("outlet_county_code")))]
        print(f"  {len(permits)} sales tax permits inside the Paris orbit")
        zips = {(p.get("outlet_zip_code") or "")[:5] for p in permits
                if (p.get("outlet_zip_code") or "").strip()}
        zips.discard("")
        town_counts = {}
        for p in permits:
            # not `town`: that is the function that spells one consistently.
            seen_town = pretty(p.get("outlet_city") or "").lower()
            if seen_town:
                town_counts[seen_town] = town_counts.get(seen_town, 0) + 1
        towns = {t for t, n in town_counts.items() if n > 1}
        print(f"  {len(zips)} postcodes and {len(towns)} towns in the trade area")

        places = get_overture(cache)
        carriers = get_carriers(cache, {t.upper() for t in town_counts})
        licences = get_licences(cache)
        salons = get_salons(cache)

        print("Statewide location counts...")
        locations = statewide_locations({p.get("taxpayer_number") for p in permits})

        # Everything is assembled in memory first, keyed by dedupe_key, so a
        # business seen by three sources is written once.
        book = {}

        def slot(name, address, city, extra_key=""):
            key = f"{norm(name)}|{street_key(address) or norm(city) or extra_key}"[:240]
            if key not in book:
                book[key] = {"dedupe_key": key, "name": pretty(name), "sources": [],
                             "people": []}
            return book[key]

        # 1. Sales tax permits: the spine.
        for row in permits:
            name = row.get("outlet_name") or row.get("taxpayer_name") or ""
            if not name.strip():
                continue
            entry = slot(name, row.get("outlet_address"), row.get("outlet_city"))
            org = (row.get("taxpayer_organization_type") or "").strip().upper()
            entry.update({
                "legal_name": pretty(row.get("taxpayer_name")),
                "address": pretty(row.get("outlet_address")),
                "city": town(row.get("outlet_city")),
                "state": row.get("outlet_state") or "TX",
                "zip_code": (row.get("outlet_zip_code") or "")[:5],
                "county": COUNTIES.get(row.get("outlet_county_code"), ""),
                "naics": (row.get("outlet_naics_code") or "")[:6],
                "industry": trade(naics_label(row.get("outlet_naics_code"))),
                "entity_type": ENTITY_TYPES.get(org, ""),
                "started_on": parse_date(row.get("outlet_first_sales_date")),
                "taxpayer_number": row.get("taxpayer_number") or "",
                "locations": locations.get(row.get("taxpayer_number"), 1),
            })
            owner = owner_from_taxpayer(row.get("taxpayer_name"), org)
            if owner:
                entry["owner_name"] = owner
            if "comptroller" not in entry["sources"]:
                entry["sources"].append("comptroller")

        # 2. Franchise taxpayers. ENRICH ONLY, never create. A registration
        #    says a company exists at the Secretary of State; it says nothing
        #    about whether anybody trades under it or would take a call, and
        #    the file is mostly holding entities, dormant shells and LLCs that
        #    exist to own one field. Creating a lead from one put five
        #    thousand uncallable names on a call sheet.
        by_name = {}
        for entry in book.values():
            by_name.setdefault(norm(entry["name"]), entry)
        for row in franchise:
            name = row.get("taxpayer_name") or ""
            entry = by_name.get(norm(name))
            if not name.strip() or entry is None:
                continue
            org = (row.get("taxpayer_organizational_type") or "").strip().upper()
            entry.setdefault("legal_name", pretty(name))
            if not entry.get("entity_type"):
                entry["entity_type"] = ENTITY_TYPES.get(org, "")
            if not entry.get("started_on"):
                entry["started_on"] = parse_date(row.get("sos_charter_date"))
            entry.setdefault("taxpayer_number", row.get("taxpayer_number") or "")
            if "franchise" not in entry["sources"]:
                entry["sources"].append("franchise")

        # 3. OpenStreetMap: the contact details.
        by_name = {}
        for entry in book.values():
            by_name.setdefault(norm(entry["name"]), entry)
        for el in osm:
            tags = el.get("tags") or {}
            name = tags.get("name") or ""
            if not name.strip():
                continue
            street = " ".join(part for part in (tags.get("addr:housenumber"),
                                                tags.get("addr:street")) if part)
            entry = by_name.get(norm(name))
            if entry is None:
                entry = slot(name, street, tags.get("addr:city"), extra_key=str(el.get("id")))
                entry.setdefault("city", town(tags.get("addr:city") or ""))
                entry.setdefault("address", pretty(street))
                entry.setdefault("zip_code", (tags.get("addr:postcode") or "")[:5])
                by_name[norm(name)] = entry
            phone = tidy_phone(tags.get("phone") or tags.get("contact:phone"))
            if phone:
                entry.setdefault("phone", phone)
            site = tidy_site(tags.get("website") or tags.get("contact:website"))
            if site:
                entry.setdefault("website", site)
            mail = (tags.get("email") or tags.get("contact:email") or "").strip().lower()
            if mail and EMAIL_RE.fullmatch(mail):
                entry.setdefault("email", mail)
            if el.get("lat") or (el.get("center") or {}).get("lat"):
                centre = el.get("center") or el
                entry.setdefault("lat", centre.get("lat"))
                entry.setdefault("lon", centre.get("lon"))
            if not entry.get("industry"):
                kind = (tags.get("shop") or tags.get("amenity") or tags.get("office")
                        or tags.get("craft") or tags.get("healthcare") or "")
                if kind and kind != "yes":
                    entry["industry"] = trade(kind.replace("_", " ").capitalize())
            entry["osm_ref"] = f"{el.get('type')}/{el.get('id')}"
            if "openstreetmap" not in entry["sources"]:
                entry["sources"].append("openstreetmap")

        # 3b. Overture places. Enriches by name first; creates only where a
        #     place has a way of being reached and a category that trades.
        by_name = {}
        for entry in book.values():
            by_name.setdefault(norm(entry["name"]), entry)
        made_here = 0
        for place in places:
            name = (place.get("name") or "").strip()
            if not name:
                continue
            try:
                if float(place.get("confidence") or 0) < 0.5:
                    continue
            except (TypeError, ValueError):
                pass
            category = (place.get("category") or "").strip().lower()
            if category in NOT_A_TRADER:
                continue
            group = overture_trade(place.get("hierarchy"))
            if not group and not category:
                continue
            addr = place.get("addresses") or {}
            city = town(addr.get("locality") or "")
            postcode = str(addr.get("postcode") or "")[:5]
            phone = next((p for p in (tidy_phone(x) for x in place.get("phones") or []) if p), "")
            site = next((s for s in (tidy_site(x) for x in place.get("websites") or []) if s), "")
            mail = next((m.strip().lower() for m in place.get("emails") or []
                         if m and EMAIL_RE.fullmatch(m.strip())), "")
            social = next((str(x) for x in place.get("socials") or [] if x), "")

            entry = by_name.get(norm(name))
            if entry is None:
                # A place with no way to reach it adds a name and nothing else.
                if not (phone or site or mail):
                    continue
                if city.upper() in FAR_TOWNS:
                    continue
                if postcode and postcode not in zips:
                    continue
                if not postcode and city.lower() not in towns:
                    continue
                entry = slot(name, addr.get("freeform"), city, extra_key=str(place.get("id")))
                entry.setdefault("address", pretty(addr.get("freeform") or ""))
                entry.setdefault("city", city)
                entry.setdefault("zip_code", postcode)
                entry.setdefault("industry", group or trade(
                    category.replace("_", " ").capitalize()))
                by_name[norm(name)] = entry
                made_here += 1
            if phone:
                entry.setdefault("phone", phone)
            if site:
                entry.setdefault("website", site)
            if mail:
                entry.setdefault("email", mail)
            if social:
                entry.setdefault("social", social[:300])
            if place.get("lat"):
                entry.setdefault("lat", place.get("lat"))
                entry.setdefault("lon", place.get("lon"))
            entry["overture_id"] = str(place.get("id") or "")[:60]
            if "overture" not in entry["sources"]:
                entry["sources"].append("overture")
        print(f"  overture: {made_here} new, the rest enriched what was there")

        # 4. Healthcare. Organisations become leads with the authorised
        #    official as the owner; individual providers become named people
        #    at whichever practice shares their street.
        by_street = {}
        for entry in book.values():
            key = (street_key(entry.get("address", "")), norm(entry.get("city", "")))
            if key[0]:
                by_street.setdefault(key, entry)
        for row in npi:
            basic = row.get("basic") or {}
            practice = next((a for a in row.get("addresses") or []
                             if a.get("address_purpose") == "LOCATION"), None)
            if not practice or (practice.get("state") or "") != "TX":
                continue
            city = town(practice.get("city") or "")
            street = practice.get("address_1") or ""
            phone = tidy_phone(practice.get("telephone_number"))
            if row.get("enumeration_type") == "NPI-2":
                name = basic.get("organization_name") or ""
                if not name.strip():
                    continue
                entry = by_name.get(norm(name)) or slot(name, street, city)
                by_name.setdefault(norm(name), entry)
                entry.setdefault("address", pretty(street))
                entry.setdefault("city", city)
                entry.setdefault("zip_code", (practice.get("postal_code") or "")[:5])
                entry.setdefault("industry", trade("Health practices"))
                if phone:
                    entry.setdefault("phone", phone)
                official = " ".join(part for part in (
                    basic.get("authorized_official_first_name"),
                    basic.get("authorized_official_last_name")) if part)
                if official:
                    entry.setdefault("owner_name", pretty(official))
                    entry["people"].append({
                        "name": pretty(official),
                        "role": pretty(basic.get("authorized_official_title_or_position") or "Authorised official"),
                        "phone": tidy_phone(basic.get("authorized_official_telephone_number")) or phone,
                        "source": "npi"})
                entry["npi"] = row.get("number") or ""
                if "npi" not in entry["sources"]:
                    entry["sources"].append("npi")
            else:
                host = by_street.get((street_key(street), norm(city)))
                if host is None:
                    continue
                person = " ".join(part for part in (basic.get("first_name"),
                                                    basic.get("last_name")) if part)
                if not person.strip():
                    continue
                taxonomy = next((t.get("desc") for t in row.get("taxonomies") or []
                                 if t.get("primary")), "")
                host["people"].append({"name": pretty(person), "role": taxonomy or "Provider",
                                       "phone": phone, "source": "npi"})
                if "npi" not in host["sources"]:
                    host["sources"].append("npi")

        # 5. Hauliers. The phone is filed with the licence and the driver
        #    count is filed with it, which makes this the only place in any of
        #    this that publishes how many people work somewhere.
        by_name = {}
        for entry in book.values():
            by_name.setdefault(norm(entry["name"]), entry)
        for row in carriers:
            name = row.get("legal_name") or ""
            if not name.strip():
                continue
            # The town field brought Austin along; the postcode does not. And
            # an inactive DOT registration is a business that has stopped,
            # which is not somebody to ring.
            if str(row.get("phy_zip") or "")[:5] not in zips:
                continue
            if not in_orbit(row.get("phy_city"), ""):
                if str(row.get("phy_city") or "").strip().upper() not in {t.upper() for t in towns}:
                    continue
            if row.get("status_code") not in ("A", "P"):
                continue
            city = town(row.get("phy_city") or "")
            entry = by_name.get(norm(name))
            if entry is None:
                entry = slot(name, row.get("phy_street"), city, extra_key=str(row.get("dot_number")))
                entry.setdefault("address", pretty(row.get("phy_street")))
                entry.setdefault("city", city)
                entry.setdefault("zip_code", (row.get("phy_zip") or "")[:5])
                entry.setdefault("industry", trade("Trucking"))
                entry.setdefault("county", "")
                by_name[norm(name)] = entry
            phone = tidy_phone(row.get("phone"))
            if phone:
                entry.setdefault("phone", phone)
            drivers = row.get("total_drivers")
            try:
                drivers = int(drivers)
            except (TypeError, ValueError):
                drivers = 0
            if drivers > 0:
                entry.setdefault("employees", drivers)
            if "fmcsa" not in entry["sources"]:
                entry["sources"].append("fmcsa")

        # 6. Trade licences. No telephone, but the owner is named, and a
        #    licensed one-man air conditioning firm is exactly the business
        #    this list exists to find.
        for row in licences:
            business = row.get("business_name") or ""
            if not business.strip():
                continue
            # The employees in this file are qualifications, not businesses.
            if str(row.get("license_type")) not in BUSINESS_LICENCES:
                continue
            owner = person_name(row.get("owner_name")) or pretty(row.get("owner_name") or "")
            licence_trade = trade(pretty(row.get("license_type") or ""))
            display = person_name(business) or pretty(business)
            entry = by_name.get(norm(display))
            if entry is None:
                entry = slot(display, "", "", extra_key=str(row.get("license_number")))
                entry["name"] = display
                entry.setdefault("industry", licence_trade)
                by_name[norm(display)] = entry
            # County comes from the query itself, so a licence row is known to
            # be in the trade area even without a town.
            entry.setdefault("county", COUNTIES.get(
                {v.upper(): k for k, v in COUNTIES.items()}.get(
                    (row.get("business_county") or "").upper(), ""), ""))
            if owner:
                entry.setdefault("owner_name", owner)
            if licence_trade and not entry.get("industry"):
                entry["industry"] = licence_trade
            if "tdlr" not in entry["sources"]:
                entry["sources"].append("tdlr")

        # 7. Salons, for their telephone numbers.
        for row in salons:
            name = row.get("business_name") or ""
            phone = tidy_phone(row.get("owner_telephone"))
            where = str(row.get("mailing_address_city_state_zip") or "").upper()
            if not name.strip() or not phone:
                continue
            entry = by_name.get(norm(name))
            if entry is None:
                match = next((t for t in towns if t.upper() + " TX" in where), None)
                if not match:
                    continue
                town_name = town(match)
                entry = slot(name, row.get("mailing_address_line1"), town_name)
                entry.setdefault("address", pretty(row.get("mailing_address_line1")))
                entry.setdefault("city", town_name)
                entry.setdefault("industry", trade("Salons and barbers"))
                by_name[norm(name)] = entry
            entry.setdefault("phone", phone)
            if "tdlr" not in entry["sources"]:
                entry["sources"].append("tdlr")

        print(f"  {len(book)} businesses assembled")

        # 5. Their own websites, once each, for a published email.
        if enrich:
            sites = [(key, entry["website"]) for key, entry in book.items()
                     if entry.get("website") and not entry.get("email")]
            print(f"Asking {len(sites)} websites for an email...")
            with ThreadPoolExecutor(max_workers=12) as pool:
                for (key, _), found in zip(sites, pool.map(lambda s: scrape_email(s[1]), sites)):
                    if found:
                        book[key]["email"] = found[:200]
            print(f"  {sum(1 for e in book.values() if e.get('email'))} have an email")

        # ── the trade area ──────────────────────────────────
        before = len(book)
        book = {k: e for k, e in book.items() if trades_here(e, towns, zips)}
        print(f"  {before - len(book)} dropped as out of area or not a business")

        # ── write ───────────────────────────────────────────
        existing = {lead.dedupe_key: lead for lead in Lead.query.all()}
        made = updated = 0
        # Columns the import owns. Everything else on the row belongs to
        # whoever is working the list.
        owned = ("name", "legal_name", "owner_name", "address", "city", "state",
                 "zip_code", "county", "lat", "lon", "phone", "email", "website",
                 "industry", "naics", "entity_type", "started_on", "locations",
                 "employees", "social", "taxpayer_number", "osm_ref",
                 "overture_id", "npi")

        for key, entry in book.items():
            lead = existing.get(key)
            if lead is None:
                lead = Lead(dedupe_key=key, name=entry["name"], stage="lead")
                db.session.add(lead)
                made += 1
            else:
                updated += 1
            for field in owned:
                value = entry.get(field)
                if value in (None, "", []):
                    continue
                # Never overwrite something a person typed over the import.
                if (field in ("phone", "email", "website", "owner_name", "employees", "social")
                        and getattr(lead, field)):
                    continue
                setattr(lead, field, value)
            # Marks the import does not own - "site", left by enrich_sites.py
            # when it read the business's own pages - survive a re-run. An
            # overwrite here would make every later pass redo its work.
            keep = [m for m in (lead.sources or "").split(",")
                    if m and m not in KNOWN_SOURCES]
            lead.sources = ",".join(entry["sources"] + keep)[:200]

            if entry["people"]:
                db.session.flush()
                have = {(p.name or "").lower() for p in lead.people}
                for order, person in enumerate(entry["people"][:8]):
                    if (person["name"] or "").lower() in have or not person["name"]:
                        continue
                    have.add(person["name"].lower())
                    db.session.add(LeadPerson(
                        lead_id=lead.id, name=person["name"][:160], role=(person.get("role") or "")[:120],
                        phone=(person.get("phone") or "")[:40], email=(person.get("email") or "")[:200],
                        source=person.get("source", "")[:60], sort_order=order))
            if (made + updated) % 500 == 0:
                db.session.commit()
        db.session.commit()

        merged = _merge_duplicates(db, Lead, LeadPerson)
        if merged:
            print(f"  {merged} duplicate rows merged into the row that knew most")

        # A row that no longer belongs, and that nobody has worked, goes.
        # One that has been rung, noted or converted stays whatever the
        # filter thinks: her work outranks the import.
        stale = [lead for lead in Lead.query.all()
                 if lead.dedupe_key not in book and not lead.touches
                 and not (lead.notes or "").strip() and not lead.client_id]
        for lead in stale:
            db.session.delete(lead)
        if stale:
            db.session.commit()
            print(f"  {len(stale)} removed as no longer in the trade area")

        total = Lead.query.count()
        with_phone = Lead.query.filter(Lead.phone != "", Lead.phone.isnot(None)).count()
        with_email = Lead.query.filter(Lead.email != "", Lead.email.isnot(None)).count()
        with_site = Lead.query.filter(Lead.website != "", Lead.website.isnot(None)).count()
        people = LeadPerson.query.count()
        print(f"\n{made} new, {updated} updated. {total} businesses on the board.")
        with_owner = Lead.query.filter(Lead.owner_name != "", Lead.owner_name.isnot(None)).count()
        with_staff = Lead.query.filter(Lead.employees.isnot(None)).count()
        # No "without a website" figure here either. Nothing checked, so the
        # only honest statement is how many are KNOWN to have one.
        print(f"  phone {with_phone} | email {with_email} | website known {with_site} "
              f"| named contacts {people}")
        with_social = Lead.query.filter(Lead.social.isnot(None), Lead.social != "").count()
        print(f"  owner named {with_owner} | headcount filed {with_staff} "
              f"| social page {with_social}")
        by_source = {}
        for lead in Lead.query.all():
            by_source[lead.sources] = by_source.get(lead.sources, 0) + 1
        for src, n in sorted(by_source.items(), key=lambda x: -x[1])[:8]:
            print(f"    {src or '(none)':34} {n}")


if __name__ == "__main__":
    cache_dir = None
    args = sys.argv[1:]
    if "--cache" in args:
        cache_dir = args[args.index("--cache") + 1]
    run(cache=cache_dir, enrich="--no-enrich" not in args)
