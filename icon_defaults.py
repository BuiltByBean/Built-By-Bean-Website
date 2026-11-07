"""The icon vocabulary's defaults: one drawing per concept.

Written from the harvest of Michael's repos on 2026-11-04 (where he already
draws the same thing for the same concept in more than one project) and his
answers on the Handbook's Icons tab. Every drawing is Heroicons v2 outline
(viewBox 0 0 24 24, stroke 1.5) unless its library says otherwise. Edits made
through the door live in IconConcept and win over these; icon_vocabulary.py
says how. Generated, then kept by hand: change a concept here and the board
changes everywhere it is drawn.
"""

DEFAULTS = [{'slug': 'legal',
             'name': 'Legal',
             'group': 'nav',
             'library': 'Heroicons outline',
             'icon_name': 'scale',
             # The Legal library (issue #42, 2026-11-07): the laws behind each
             # product's decisions. A balance, because the Handbook already
             # wears the cap and Contracts the checked document.
             'svg': '<path d="M12 3v17.25m0 0c-1.472 0-2.882.265-4.185.75M12 20.25c1.472 0 2.882.265 4.185.75M18.75 4.5c-1.468 0-2.88.266-4.185.75m4.185-.75c1.146 0 2.254.187 3.312.533m-3.312-.533l2.86 10.027a.75.75 0 0 1-.247.83 6.75 6.75 0 0 1-6.627 0 .75.75 0 0 1-.247-.83L18.75 4.5M5.25 4.5c1.468 0 2.88.266 4.185.75M5.25 4.5c-1.146 0-2.254.187-3.312.533m3.312-.533l2.86 10.027a.75.75 0 0 1-.247.83 6.75 6.75 0 0 1-6.627 0 .75.75 0 0 1-.247-.83L5.25 4.5"/>',
             'aliases': 'law, laws, compliance, lawyer, statutes, legal library',
             'used_in_md': 'BBB Legal: the library of the laws behind each product, with the proof copies',
             'never_md': 'contracts (document-check); handbook (academic-cap)'},
            {'slug': 'notifications',
  'name': 'Notifications',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'bell',
  'svg': '<path d="M14.857 17.082a23.848 23.848 0 0 0 5.454-1.31A8.967 8.967 0 0 1 18 9.75V9A6 6 0 0 0 6 '
         '9v.75a8.967 8.967 0 0 1-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 0 '
         '1-5.714 0m5.714 0a3 3 0 1 1-5.714 0"/>',
  'aliases': 'needs attention, alerts, needs me, notify, reminders',
  'used_in_md': 'BBB Needs attention, EntertainHQ and Talent Booker bell (same path); Kuper and Piped draw a '
                'bell for Needs me',
  'never_md': "messages (a person talking to you); what's new (sparkles)"},
 {'slug': 'catalog',
  'name': 'Catalog',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'briefcase',
  'svg': '<path d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 0 0 .75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 0 0-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0 1 12 15.75c-2.648 0-5.195-.429-7.577-1.22a2.016 2.016 0 0 1-.673-.38m0 0A2.18 2.18 0 0 1 3 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 0 1 3.413-.387m7.5 0V5.25A2.25 2.25 0 0 0 13.5 3h-3a2.25 2.25 0 0 0-2.25 2.25v.894m7.5 0a48.667 48.667 0 0 0-7.5 0M12 12.75h.008v.008H12v-.008Z"/>',
  'aliases': 'portfolio, showcase, my work, work samples',
  'used_in_md': 'BBB Catalog, the private showcase of approved apps sent to prospects (issue #23, 2026-11-06)',
  'never_md': 'apps (the stack of windows, every app on the board); package (a product sold)'},
 {'slug': 'workspace',
  'name': 'Workspace',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'inbox',
  'svg': '<path d="M2.25 13.5h3.86a2.25 2.25 0 0 1 2.012 1.244l.256.512a2.25 2.25 0 0 0 2.013 '
         '1.244h3.218a2.25 2.25 0 0 0 2.013-1.244l.256-.512a2.25 2.25 0 0 1 '
         '2.013-1.244h3.859m-19.5.338V18a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 '
         '18v-4.162c0-.224-.034-.447-.1-.661L19.24 5.338a2.25 2.25 0 0 0-2.15-1.588H6.911a2.25 2.25 0 0 '
         '0-2.15 1.588L2.35 13.177a2.25 2.25 0 0 0-.1.661Z"/>',
  'aliases': 'tasks, messages and projects in one place, to do, backlog',
  'used_in_md': 'EntertainHQ and Talent Booker Workspace; his pick 2026-11-04: tasks wear it too, because '
                'tasks live in the Workspace, here and on the board',
  'never_md': 'messages (chat bubbles); support (bug)'},
 {'slug': 'messages',
  'name': 'Messages',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'chat-bubble-left-right',
  'svg': '<path d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 '
         '2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 0 '
         '1-.825-.242m9.345-8.334a2.126 2.126 0 0 0-.476-.095 48.64 48.64 0 0 0-8.048 0c-1.131.094-1.976 '
         '1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 '
         '1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0 0 11.25 3c-2.115 '
         '0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 '
         '1.157.14 1.74.194V21l4.155-4.155"/>',
  'aliases': 'chat, conversations, team chat, DMs',
  'used_in_md': 'BBB Workspace before 2026-11-04; EntertainHQ draws a message line with it',
  'never_md': 'texting (one bubble with dots); notifications (bell); workspace (inbox)'},
 {'slug': 'projects',
  'name': 'Projects',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'folder',
  'svg': '<path d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 '
         '12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 '
         '2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 '
         '1-1.06-.44Z"/>',
  'aliases': 'builds, jobs',
  'used_in_md': 'a folder in Robinson, Data Dungeon and BBB',
  'never_md': 'documents (one page)'},
 {'slug': 'businesses',
  'name': 'Businesses',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'building-office',
  'svg': '<path d="M3.75 21h16.5M4.5 3h15M5.25 3v18m13.5-18v18M9 6.75h1.5m-1.5 3h1.5m-1.5 3h1.5m3-6H15m-1.5 '
         '3H15m-1.5 3H15M9 21v-3.375c0-.621.504-1.125 1.125-1.125h3.75c.621 0 1.125.504 1.125 1.125V21"/>',
  'aliases': 'companies, LLCs, command center',
  'used_in_md': 'BBB Businesses (only app with the page)',
  'never_md': 'venue (building-office-2 in EntertainHQ); bank (columns)'},
 {'slug': 'clients',
  'name': 'Clients',
  'group': 'nav',
  'library': 'Heroicons v1 outline',
  'icon_name': 'user-group (side heads trimmed)',
  'svg': '<path d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 '
         '3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 '
         '3 3 0 016 0z"/>',
  'aliases': 'customers, accounts',
  'used_in_md': 'BBB Clients and Personal-Trainer clients, the same path',
  'never_md': 'users (one person); profile (identification card)'},
 {'slug': 'leads',
  'name': 'Leads',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'megaphone',
  'svg': '<path d="M10.34 15.84c-.688-.06-1.386-.09-2.09-.09H7.5a4.5 4.5 0 1 1 0-9h.75c.704 0 1.402-.03 '
         '2.09-.09m0 9.18c.253.962.584 1.892.985 2.783.247.55.06 1.21-.463 '
         '1.511l-.657.38c-.551.318-1.26.117-1.527-.461a20.845 20.845 0 0 1-1.44-4.282m3.102.069a18.03 18.03 '
         '0 0 1-.59-4.59c0-1.586.205-3.124.59-4.59m0 9.18a23.848 23.848 0 0 1 8.835 2.535M10.34 6.66a23.847 '
         '23.847 0 0 0 8.835-2.535m0 0A23.74 23.74 0 0 0 18.795 3m.38 1.125a23.91 23.91 0 0 1 1.014 '
         '5.395m-1.014 8.855c-.118.38-.245.754-.38 1.125m.38-1.125a23.91 23.91 0 0 0 '
         '1.014-5.395m0-3.46c.495.413.811 1.035.811 1.73 0 .695-.316 1.317-.811 1.73m0-3.46a24.347 24.347 0 '
         '0 1 0 3.46"/>',
  'aliases': 'prospects, marketing, call list, casting calls',
  'used_in_md': 'BBB Leads (a megaphone, nothing else on the board is one)',
  'never_md': "what's new (sparkles; Data Dungeon drew it with a megaphone); add (EntertainHQ's admin drew "
              'Prospects with a plus)'},
 {'slug': 'support',
  'name': 'Support',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'bug-ant',
  'svg': '<path d="M12 12.75c1.148 0 2.278.08 3.383.237 1.037.146 1.866.966 1.866 2.013 0 3.728-2.35 '
         '6.75-5.25 6.75S6.75 18.728 6.75 15c0-1.046.83-1.867 1.866-2.013A24.204 24.204 0 0 1 12 12.75Zm0 '
         '0c2.883 0 5.647.508 8.207 1.44a23.91 23.91 0 0 1-1.152 6.06M12 12.75c-2.883 0-5.647.508-8.208 '
         '1.44.125 2.104.52 4.136 1.153 6.06M12 12.75a2.25 2.25 0 0 0 2.248-2.354M12 12.75a2.25 2.25 0 0 '
         '1-2.248-2.354M12 8.25c.995 0 1.971-.08 2.922-.236.403-.066.74-.358.795-.762a3.778 3.778 0 0 '
         '0-.399-2.25M12 8.25c-.995 0-1.97-.08-2.922-.236-.402-.066-.74-.358-.795-.762a3.734 3.734 0 0 1 '
         '.4-2.253M12 8.25a2.25 2.25 0 0 0-2.248 2.146M12 8.25a2.25 2.25 0 0 1 2.248 2.146M8.683 5a6.032 '
         '6.032 0 0 1-1.155-1.002c.07-.63.27-1.222.574-1.747m.581 2.749A3.75 3.75 0 0 1 15.318 5m0 '
         '0c.427-.283.815-.62 1.155-.999a4.471 4.471 0 0 0-.575-1.752M4.921 6a24.048 24.048 0 0 0-.392 '
         '3.314c1.668.546 3.416.914 5.223 1.082M19.08 6c.205 1.08.337 2.187.392 3.314a23.882 23.882 0 0 '
         '1-5.223 1.082"/>',
  'aliases': 'client support, tickets, help desk, support desk, report a bug',
  'used_in_md': 'his pick 2026-11-04, from EntertainHQ Tickets and Report a bug',
  'never_md': 'help (question mark, a hint on a page); workspace (inbox)'},
 {'slug': 'contracts',
  'name': 'Contracts',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'document-check',
  'svg': '<path d="M10.125 2.25h-4.5c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 '
         '1.125h12.75c.621 0 1.125-.504 1.125-1.125v-9M10.125 2.25h.375a9 9 0 0 1 9 9v.375M10.125 2.25A3.375 '
         '3.375 0 0 1 13.5 5.625v1.5c0 .621.504 1.125 1.125 1.125h1.5a3.375 3.375 0 0 1 3.375 3.375M9 '
         '15l2.25 2.25L15 12"/>',
  'aliases': 'e-signature, SOW, agreements, signing',
  'used_in_md': 'BBB Contracts and the EntertainHQ / Talent Booker Signing page, the same path',
  'never_md': 'invoices (document with lines); sign (check-badge, the act of signing)'},
 {'slug': 'mvp-builder',
  'name': 'MVP Builder',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'wrench',
  'svg': '<path d="M21.75 6.75a4.5 4.5 0 0 1-4.884 4.484c-1.076-.091-2.264.071-2.95.904l-7.152 8.684a2.548 '
         '2.548 0 1 1-3.586-3.586l8.684-7.152c.833-.686.995-1.874.904-2.95a4.5 4.5 0 0 1 6.336-4.486l-3.276 '
         '3.276a3.004 3.004 0 0 0 2.25 2.25l3.276-3.276c.256.565.398 1.192.398 1.852Z"/><path d="M4.867 '
         '19.125h.008v.008h-.008v-.008Z"/>',
  'aliases': 'packages, build prompt, scoping',
  'used_in_md': "BBB MVP Builder; Kuper and Piped use a wrench for Jobs (a trade app's work)",
  'never_md': 'settings (cog)'},
 {'slug': 'apps',
  'name': 'Apps',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'rectangle-stack',
  'svg': '<path d="M6 6.878V6a2.25 2.25 0 0 1 2.25-2.25h7.5A2.25 2.25 0 0 1 18 6v.878m-12 '
         '0c.235-.083.487-.128.75-.128h10.5c.263 0 .515.045.75.128m-12 0A2.25 2.25 0 0 0 4.5 '
         '9v.878m13.5-3A2.25 2.25 0 0 1 19.5 9v.878m0 0a2.246 2.246 0 0 0-.75-.128H5.25c-.263 '
         '0-.515.045-.75.128m15 0A2.25 2.25 0 0 1 21 12v6a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 '
         '18v-6c0-.98.626-1.813 1.5-2.122"/>',
  'aliases': 'my apps, products, launcher',
  'used_in_md': 'his pick 2026-11-04: a stack of windows for My Apps, because the grid is the dashboard',
  'never_md': 'dashboard (grid); workspace (inbox)'},
 {'slug': 'dashboard',
  'name': 'Dashboard',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'squares-2x2',
  'svg': '<path d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 '
         '2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 '
         '2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 '
         '2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 '
         '1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 '
         '1 18 20.25h-2.25A2.25 2.25 0 0 1 13.5 18v-2.25Z"/>',
  'aliases': 'home, overview of an app',
  'used_in_md': 'his pick 2026-11-04; EntertainHQ admin, Robinson and Data Dungeon already draw Dashboard '
                'this way',
  'never_md': 'apps (stack of windows); finances (pie)'},
 {'slug': 'handbook',
  'name': 'Handbook',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'academic-cap',
  'svg': '<path d="M4.26 10.147a60.438 60.438 0 0 0-.491 6.347A48.62 48.62 0 0 1 12 20.904a48.62 48.62 0 0 1 '
         '8.232-4.41 60.46 60.46 0 0 0-.491-6.347m-15.482 0a50.636 50.636 0 0 0-2.658-.813A59.906 59.906 0 0 '
         '1 12 3.493a59.903 59.903 0 0 1 10.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.717 50.717 0 '
         '0 1 12 13.489a50.702 50.702 0 0 1 7.74-3.342M6.75 15a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm0 '
         '0v-3.675A55.378 55.378 0 0 1 12 8.443m-7.007 11.55A5.981 5.981 0 0 0 6.75 15.75v-1.5"/>',
  'aliases': 'best practices, rules, playbooks, guide, tutorial',
  'used_in_md': 'BBB Handbook, EntertainHQ tutorial',
  'never_md': 'books (open book)'},
 {'slug': 'time',
  'name': 'Time',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'clock',
  'svg': '<path d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>',
  'aliases': 'time tracking, hours, timer, pending',
  'used_in_md': 'a clock in every repo; Kuper, Piped and Robinson the same path',
  'never_md': 'calendar (a date, not a duration); history (a record of changes)'},
 {'slug': 'finances',
  'name': 'Finances',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'chart-pie',
  'svg': '<path d="M10.5 6a7.5 7.5 0 1 0 7.5 7.5h-7.5V6Z"/><path d="M13.5 10.5H21A7.5 7.5 0 0 0 13.5 '
         '3v7.5Z"/>',
  'aliases': 'overview, dashboard, money at a glance',
  'used_in_md': "his pick 2026-11-04, the board's Dashboard; EntertainHQ draws Financials as a bar chart, "
                'Kuper and Piped a dollar in a circle',
  'never_md': 'reports (bar chart)'},
 {'slug': 'books',
  'name': 'Books',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'book-open',
  'svg': '<path d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 '
         '18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 '
         '8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25"/>',
  'aliases': 'ledger, bookkeeping, monthly close',
  'used_in_md': 'BBB Books; EntertainHQ uses an open book for House Rules',
  'never_md': 'handbook (academic cap)'},
 {'slug': 'invoices',
  'name': 'Invoices',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'document-text',
  'svg': '<path d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 '
         '7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 '
         '0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 '
         '1.125-1.125V11.25a9 9 0 0 0-9-9Z"/>',
  'aliases': 'billing, bills sent, outstanding',
  'used_in_md': 'BBB Invoices; Piped draws a ruled invoice page',
  'never_md': 'contracts (document-check); expenses (receipt)'},
 {'slug': 'taxes',
  'name': 'Taxes',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'receipt-percent',
  'svg': '<path d="m9 14.25 6-6m4.5-3.493V21.75l-3.75-1.5-3.75 1.5-3.75-1.5-3.75 1.5V4.757c0-1.108.806-2.057 '
         '1.907-2.185a48.507 48.507 0 0 1 11.186 0c1.1.128 1.907 1.077 1.907 2.185ZM9.75 '
         '9h.008v.008H9.75V9Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm4.125 '
         '4.5h.008v.008h-.008V13.5Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z"/>',
  'aliases': 'sales tax, returns, franchise tax, estimates',
  'used_in_md': 'BBB Taxes',
  'never_md': 'expenses (plain receipt)'},
 {'slug': 'expenses',
  'name': 'Expenses',
  'group': 'nav',
  'library': 'Lucide',
  'icon_name': 'receipt',
  'svg': '<path d="M5 3h14a1 1 0 0 1 1 1v17l-3-2-3 2-3-2-3 2-3-2V4a1 1 0 0 1 1-1z"/><path d="M8 8h8"/><path '
         'd="M8 12h8"/>',
  'aliases': 'spending, costs, money out, receipts',
  'used_in_md': 'a receipt for money out in Kuper, Piped, Data Dungeon and Robinson (Kuper: a receipt is '
                'money out, money is what comes in)',
  'never_md': 'revenue (banknotes); taxes (receipt with a percent); payments (card)'},
 {'slug': 'hosting',
  'name': 'Hosting',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'server-stack',
  'svg': '<path d="M5.25 14.25h13.5m-13.5 0a3 3 0 0 1-3-3m3 3a3 3 0 1 0 0 6h13.5a3 3 0 1 0 0-6m-16.5-3a3 3 0 '
         '0 1 3-3h13.5a3 3 0 0 1 3 3m-19.5 0a4.5 4.5 0 0 1 .9-2.7L5.737 5.1a3.375 3.375 0 0 1 '
         '2.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 0 1 .9 2.7m0 0a3 3 0 0 1-3 3m0 '
         '3h.008v.008h-.008v-.008Zm0-6h.008v.008h-.008v-.008Zm-3 '
         '6h.008v.008h-.008v-.008Zm0-6h.008v.008h-.008v-.008Z"/>',
  'aliases': 'servers, Railway, hosting fees',
  'used_in_md': 'BBB Hosting',
  'never_md': 'vendors (storefront)'},
 {'slug': 'users',
  'name': 'Users',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'user',
  'svg': '<path d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 '
         '0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z"/>',
  'aliases': 'team, people, logins, one person',
  'used_in_md': 'BBB Users; EntertainHQ draws Contact info with it',
  'never_md': 'clients (group); profile (identification card); roles (shield)'},
 {'slug': 'org',
  'name': 'Org',
  'group': 'nav',
  'library': 'EntertainHQ',
  'icon_name': 'org chart (three boxes)',
  'svg': '<path d="M9.75 3.75h4.5v4.5h-4.5zM3.75 15.75h4.5v4.5h-4.5zM15.75 15.75h4.5v4.5h-4.5zM12 '
         '8.25V12m-6 3.75V12h12v3.75"/>',
  'aliases': 'organization, org chart, team, people of a business, roles and responsibilities',
  'used_in_md': 'EntertainHQ admin Organization; BBB Org (was Team), 2026-11-04',
  'never_md': 'users (one person, a login); clients (group); businesses (building)'},
 {'slug': 'bank',
  'name': 'Bank',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'building-library',
  'svg': '<path d="M12 21v-8.25M15.75 21v-8.25M8.25 21v-8.25M3 9l9-6 9 6m-1.5 12V10.332A48.36 48.36 0 0 0 12 '
         '9.75c-2.551 0-5.056.2-7.5.582V21M3 21h18M12 6.75h.008v.008H12V6.75Z"/>',
  'aliases': 'bank lines, Mercury, statements',
  'used_in_md': 'none yet',
  'never_md': 'businesses (office building)'},
 {'slug': 'settings',
  'name': 'Settings',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'cog-6-tooth',
  'svg': '<path d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 '
         '1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 '
         '1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 '
         '1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 '
         '.255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 '
         '1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 '
         '1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 '
         '0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 '
         '1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 '
         '1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 '
         '6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 '
         '1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 '
         '1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z"/><path d="M15 12a3 3 0 '
         '1 1-6 0 3 3 0 0 1 6 0Z"/>',
  'aliases': 'configure, preferences, app settings',
  'used_in_md': 'a gear in EntertainHQ, Personal-Trainer, Kuper, Piped, Robinson and BBB',
  'never_md': 'mvp builder (wrench)'},
 {'slug': 'calendar',
  'name': 'Calendar',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'calendar',
  'svg': '<path d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 '
         '7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 '
         '5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5"/>',
  'aliases': 'dates, schedule, monthly, bookings, deadlines',
  'used_in_md': 'EntertainHQ, Personal-Trainer, Kuper, Piped, Robinson, BBB and Signadoc',
  'never_md': 'time (clock)'},
 {'slug': 'business-map',
  'name': 'Business map',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'map',
  'svg': '<path d="M9 6.75V15m6-6v8.25m.503 3.498 '
         '4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 '
         '1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 0 0-1.006 0L3.622 5.689C3.24 5.88 3 6.27 '
         '3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 '
         '2.497c.317.158.69.158 1.006 0Z"/>',
  'aliases': 'network, how it all connects',
  'used_in_md': 'BBB business map',
  'never_md': 'share (the three-dot network); location (pin)'},
 {'slug': 'reports',
  'name': 'Reports',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'chart-bar',
  'svg': '<path d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 '
         '6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 '
         '1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 '
         '1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 '
         '4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z"/>',
  'aliases': 'analytics, charts, stats',
  'used_in_md': 'a bar chart in EntertainHQ, Kuper, Piped, Robinson and Data Dungeon',
  'never_md': 'finances (pie)'},
 {'slug': 'profile',
  'name': 'Profile',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'identification',
  'svg': '<path d="M15 9h3.75M15 12h3.75M15 15h3.75M4.5 19.5h15a2.25 2.25 0 0 0 2.25-2.25V6.75A2.25 2.25 0 0 '
         '0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25v10.5A2.25 2.25 0 0 0 4.5 19.5Zm6-10.125a1.875 1.875 0 1 '
         '1-3.75 0 1.875 1.875 0 0 1 3.75 0Zm1.294 6.336a6.721 6.721 0 0 1-3.17.789 6.721 6.721 0 0 '
         '1-3.168-.789 3.376 3.376 0 0 1 6.338 0Z"/>',
  'aliases': 'account, my details, contact card',
  'used_in_md': 'EntertainHQ profile',
  'never_md': 'users (one person); clients'},
 {'slug': 'history',
  'name': 'History',
  'group': 'nav',
  'library': 'Heroicons outline',
  'icon_name': 'document-magnifying-glass',
  'svg': '<path d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 '
         '7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m5.231 13.481L15 17.25m-4.5-15H5.625c-.621 '
         '0-1.125.504-1.125 1.125v16.5c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 '
         '1.125-1.125V11.25a9 9 0 0 0-9-9Zm3.75 11.625a2.625 2.625 0 1 1-5.25 0 2.625 2.625 0 0 1 5.25 0Z"/>',
  'aliases': 'activity, audit log, what changed',
  'used_in_md': 'EntertainHQ History',
  'never_md': 'search (magnifying glass alone); time (clock)'},
 {'slug': 'add',
  'name': 'Add',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'plus-circle',
  'svg': '<path d="M12 9v6m3-3H9m12 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>',
  'aliases': 'new, create',
  'used_in_md': 'his pick AD2 (EntertainHQ action sheet); a plain plus in BBB, Kuper, Piped and Robinson '
                'before',
  'never_md': 'leads (EntertainHQ admin drew Prospects as a plus)'},
 {'slug': 'add-person',
  'name': 'Add a person',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'user-plus',
  'svg': '<path d="M18 7.5v3m0 0v3m0-3h3m-3 0h-3m-2.25-4.125a3.375 3.375 0 1 1-6.75 0 3.375 3.375 0 0 1 6.75 '
         '0ZM3 19.235v-.11a6.375 6.375 0 0 1 12.75 0v.109A12.318 12.318 0 0 1 9.374 21c-2.331 '
         '0-4.512-.645-6.374-1.766Z"/>',
  'aliases': 'put people on, invite, assign',
  'used_in_md': 'his pick PP1',
  'never_md': ''},
 {'slug': 'edit',
  'name': 'Edit',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'pencil-square',
  'svg': '<path d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 '
         '1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0 1 '
         '15.75 21H5.25A2.25 2.25 0 0 1 3 18.75V8.25A2.25 2.25 0 0 1 5.25 6H10"/>',
  'aliases': 'change, revise',
  'used_in_md': 'his pick E3; pencil on a square in BBB and Personal-Trainer too',
  'never_md': 'sign (check-badge)'},
 {'slug': 'delete',
  'name': 'Delete',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'trash',
  'svg': '<path d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 '
         '19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 '
         '48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 '
         '0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 '
         '2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"/>',
  'aliases': 'bin',
  'used_in_md': 'his pick D1; EntertainHQ, BBB, Personal-Trainer, Piped',
  'never_md': 'remove (circled x, takes it off without destroying it); close (x)'},
 {'slug': 'remove',
  'name': 'Remove',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'x-circle',
  'svg': '<path d="m9.75 9.75 4.5 4.5m0-4.5-4.5 4.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>',
  'aliases': 'cancel, decline, clear filters, take off',
  'used_in_md': 'his picks R4, CA2 and DE2; BBB clear filters',
  'never_md': 'close (plain x); delete (bin)'},
 {'slug': 'close',
  'name': 'Close',
  'group': 'action',
  'library': 'Heroicons v1 outline',
  'icon_name': 'x',
  'svg': '<path d="M6 18L18 6M6 6l12 12"/>',
  'aliases': 'dismiss, x',
  'used_in_md': 'his pick CL1; the same path in BBB, EntertainHQ and Personal-Trainer, the same strokes '
                'everywhere else',
  'never_md': 'remove (circled x); delete (bin)'},
 {'slug': 'back',
  'name': 'Back',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-left',
  'svg': '<path d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18"/>',
  'aliases': 'return, previous',
  'used_in_md': 'his pick BK1; Data Dungeon and the Piped site too (BBB and Kuper drew a chevron before)',
  'never_md': 'forward (chevron); reply (u-turn)'},
 {'slug': 'forward',
  'name': 'Open',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'chevron-right',
  'svg': '<path d="m8.25 4.5 7.5 7.5-7.5 7.5"/>',
  'aliases': 'next, go to, drill in',
  'used_in_md': '',
  'never_md': 'send (circled arrow); back (arrow)'},
 {'slug': 'expand',
  'name': 'Expand',
  'group': 'action',
  'library': 'Heroicons v1 outline',
  'icon_name': 'chevron-down',
  'svg': '<path d="M19 9l-7 7-7-7"/>',
  'aliases': 'dropdown, fold, open a row, show more',
  'used_in_md': 'his pick EX1: Heroicons v1 chevron-down is THE dropdown arrow',
  'never_md': ''},
 {'slug': 'search',
  'name': 'Search',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'magnifying-glass',
  'svg': '<path d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z"/>',
  'aliases': 'find, look up',
  'used_in_md': 'his pick SR1; seven repos',
  'never_md': 'history (magnifying glass on a document)'},
 {'slug': 'filter',
  'name': 'Filter',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'adjustments-horizontal',
  'svg': '<path d="M10.5 6h9.75M10.5 6a1.5 1.5 0 1 1-3 0m3 0a1.5 1.5 0 1 0-3 0M3.75 6H7.5m3 12h9.75m-9.75 '
         '0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 '
         '1.5 0 0 0-3 0m-9.75 0h9.75"/>',
  'aliases': 'filters, narrow',
  'used_in_md': 'his pick FL2 (EntertainHQ); Piped drew a funnel before',
  'never_md': ''},
 {'slug': 'menu',
  'name': 'Menu',
  'group': 'action',
  'library': 'Heroicons v1 outline',
  'icon_name': 'menu',
  'svg': '<path d="M4 6h16M4 12h16M4 18h16"/>',
  'aliases': 'hamburger, open the sidebar',
  'used_in_md': 'the same path in BBB, Personal-Trainer and Talent Booker',
  'never_md': "more (dots, a row's actions); notes (lines of text)"},
 {'slug': 'more',
  'name': 'More',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'ellipsis-horizontal',
  'svg': '<path d="M6.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM12.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 '
         '1.5 0ZM18.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Z"/>',
  'aliases': 'row actions, overflow',
  'used_in_md': 'his pick MN2; EntertainHQ, Piped, Data Dungeon',
  'never_md': 'drag (six dots)'},
 {'slug': 'sign-out',
  'name': 'Sign out',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-left-on-rectangle',
  'svg': '<path d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 '
         '7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15M12 9l-3 3m0 0 3 3m-3-3h12.75"/>',
  'aliases': 'log out, logout',
  'used_in_md': 'EntertainHQ and Talent Booker top bar, drawer and admin portal',
  'never_md': 'sign in (arrow into the door); external link'},
 {'slug': 'sign-in',
  'name': 'Sign in',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-right-end-on-rectangle',
  'svg': '<path d="M8.25 9V5.25A2.25 2.25 0 0 1 10.5 3h6a2.25 2.25 0 0 1 2.25 2.25v13.5A2.25 2.25 0 0 1 16.5 '
         '21h-6a2.25 2.25 0 0 1-2.25-2.25V15M12 9l3 3m0 0-3 3m3-3H2.25"/>',
  'aliases': 'log in, login',
  'used_in_md': 'Piped site',
  'never_md': 'sign out'},
 {'slug': 'download',
  'name': 'Download',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-down-tray',
  'svg': '<path d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 '
         '0L7.5 12m4.5 4.5V3"/>',
  'aliases': 'export, save a file',
  'used_in_md': 'his pick DL1; six repos',
  'never_md': ''},
 {'slug': 'upload',
  'name': 'Upload',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-up-tray',
  'svg': '<path d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 '
         '4.5 4.5M12 3v13.5"/>',
  'aliases': 'attach a file, import',
  'used_in_md': 'his pick UP1; six repos',
  'never_md': 'download'},
 {'slug': 'copy',
  'name': 'Copy',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'square-2-stack',
  'svg': '<path d="M16.5 8.25V6a2.25 2.25 0 0 0-2.25-2.25H6A2.25 2.25 0 0 0 3.75 6v8.25A2.25 2.25 0 0 0 6 '
         '16.5h2.25m8.25-8.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-7.5A2.25 2.25 0 0 1 '
         '8.25 18v-1.5m8.25-8.25h-6a2.25 2.25 0 0 0-2.25 2.25v6"/>',
  'aliases': 'duplicate, clipboard',
  'used_in_md': 'his pick C2; two squares in five repos',
  'never_md': ''},
 {'slug': 'external',
  'name': 'External link',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-top-right-on-square',
  'svg': '<path d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 '
         '18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25"/>',
  'aliases': 'open in a new tab, visit site',
  'used_in_md': 'BBB, EntertainHQ, Kuper, Data Dungeon',
  'never_md': ''},
 {'slug': 'refresh',
  'name': 'Refresh',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-path',
  'svg': '<path d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 '
         '0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99"/>',
  'aliases': 'sync, resync, check now, recalculate',
  'used_in_md': 'BBB drew two refresh arrows before; Piped and Data Dungeon a rotate arrow',
  'never_md': 'recurring (arrows in a square); resend (u-turn)'},
 {'slug': 'send',
  'name': 'Send',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-right-circle',
  'svg': '<path d="m12.75 15 3-3m0 0-3-3m3 3h-7.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>',
  'aliases': 'submit, send for signature, post',
  'used_in_md': 'his pick SE3 (BBB drew a paper plane before)',
  'never_md': 'forward (chevron); resend'},
 {'slug': 'resend',
  'name': 'Resend',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-uturn-right',
  'svg': '<path d="m15 15 6-6m0 0-6-6m6 6H9a6 6 0 0 0 0 12h3"/>',
  'aliases': 'send again',
  'used_in_md': 'his pick RS2',
  'never_md': ''},
 {'slug': 'reply',
  'name': 'Reply',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-uturn-left',
  'svg': '<path d="M9 15 3 9m0 0 6-6M3 9h12a6 6 0 0 1 0 12h-3"/>',
  'aliases': 'undo, answer',
  'used_in_md': 'his pick UN1',
  'never_md': 'back (arrow)'},
 {'slug': 'link',
  'name': 'Link',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'link',
  'svg': '<path d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 '
         '1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 '
         '1.242 7.244"/>',
  'aliases': 'map to, connect, attach to a record',
  'used_in_md': 'his pick (provisional)',
  'never_md': ''},
 {'slug': 'attach',
  'name': 'Attachment',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'paper-clip',
  'svg': '<path d="m18.375 12.739-7.693 7.693a4.5 4.5 0 0 1-6.364-6.364l10.94-10.94A3 3 0 1 1 19.5 '
         '7.372L8.552 18.32m.009-.01-.01.01m5.699-9.941-7.81 7.81a1.5 1.5 0 0 0 2.112 2.13"/>',
  'aliases': 'attach, receipt attached, file on it',
  'used_in_md': 'his pick AT1; BBB and EntertainHQ',
  'never_md': ''},
 {'slug': 'view',
  'name': 'View',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'eye',
  'svg': '<path d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 '
         '9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 '
         '0-8.573-3.007-9.963-7.178Z"/><path d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"/>',
  'aliases': 'preview, what they see, read',
  'used_in_md': 'his pick V1',
  'never_md': ''},
 {'slug': 'print',
  'name': 'Print',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'printer',
  'svg': '<path d="M6.72 13.829c-.24.03-.48.062-.72.096m.72-.096a42.415 42.415 0 0 1 10.56 0m-10.56 0L6.34 '
         '18m10.94-4.171c.24.03.48.062.72.096m-.72-.096L17.66 18m0 0 .229 2.523a1.125 1.125 0 0 1-1.12 '
         '1.227H7.231c-.662 0-1.18-.568-1.12-1.227L6.34 18m11.318 0h1.091A2.25 2.25 0 0 0 21 '
         '15.75V9.456c0-1.081-.768-2.015-1.837-2.175a48.055 48.055 0 0 0-1.913-.247M6.34 18H5.25A2.25 2.25 0 '
         '0 1 3 15.75V9.456c0-1.081.768-2.015 1.837-2.175a48.041 48.041 0 0 1 1.913-.247m10.5 0a48.536 '
         '48.536 0 0 0-10.5 0m10.5 0V3.375c0-.621-.504-1.125-1.125-1.125h-8.25c-.621 0-1.125.504-1.125 '
         '1.125v3.659M18 10.5h.008v.008H18V10.5Zm-3 0h.008v.008H15V10.5Z"/>',
  'aliases': 'save as PDF',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'done',
  'name': 'Done',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'check-circle',
  'svg': '<path d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>',
  'aliases': 'save, approve, check in, all clear, success, nothing waiting',
  'used_in_md': 'his picks SV2, AP2, MD2 and CI3; BBB Nothing is waiting on you',
  'never_md': 'check (a plain tick, a picked option); verify (flask); sign (badge)'},
 {'slug': 'check',
  'name': 'Picked',
  'group': 'action',
  'library': 'Built by Bean',
  'icon_name': 'tick',
  'svg': '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  'aliases': 'tick, selected, checkbox, chosen',
  'used_in_md': 'the same hand-drawn tick in Ideas, Lets-Cook, Piped, Kuper, EntertainHQ signup and Signadoc',
  'never_md': 'done (circled tick, an action)'},
 {'slug': 'sign',
  'name': 'Sign',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'check-badge',
  'svg': '<path d="M9 12.75 11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 0 1-1.043 '
         '3.296 3.745 3.745 0 0 1-3.296 1.043A3.745 3.745 0 0 1 12 21c-1.268 0-2.39-.63-3.068-1.593a3.746 '
         '3.746 0 0 1-3.296-1.043 3.745 3.745 0 0 1-1.043-3.296A3.745 3.745 0 0 1 3 12c0-1.268.63-2.39 '
         '1.593-3.068a3.745 3.745 0 0 1 1.043-3.296 3.746 3.746 0 0 1 3.296-1.043A3.746 3.746 0 0 1 12 '
         '3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 0 1 3.296 1.043 3.746 3.746 0 0 1 1.043 3.296A3.745 '
         '3.745 0 0 1 21 12Z"/>',
  'aliases': 'e-sign, signature',
  'used_in_md': 'his pick SG3',
  'never_md': 'contracts (the page); done'},
 {'slug': 'place-fields',
  'name': 'Place fields',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'cursor-arrow-rays',
  'svg': '<path d="M15.042 21.672 13.684 16.6m0 0-2.51 2.225.569-9.47 5.227 7.917-3.286-.672ZM12 '
         '2.25V4.5m5.834.166-1.591 1.591M20.25 10.5H18M7.757 14.743l-1.59 1.59M6 '
         '10.5H3.75m4.007-4.243-1.59-1.59"/>',
  'aliases': 'where to sign, signature fields',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'share',
  'name': 'Share',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'share',
  'svg': '<path d="M7.217 10.907a2.25 2.25 0 1 0 0 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 '
         '1.093m0-2.186 9.566-5.314m-9.566 7.5 9.566 5.314m0 0a2.25 2.25 0 1 0 3.935 2.186 2.25 2.25 0 0 '
         '0-3.935-2.186Zm0-12.814a2.25 2.25 0 1 0 3.933-2.185 2.25 2.25 0 0 0-3.933 2.185Z"/>',
  'aliases': 'send a link to',
  'used_in_md': 'his pick SH1; EntertainHQ, Kuper and Piped',
  'never_md': 'business map'},
 {'slug': 'power',
  'name': 'Switch off',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'power',
  'svg': '<path d="M5.636 5.636a9 9 0 1 0 12.728 0M12 3v9"/>',
  'aliases': 'retire, deactivate, disable, restore, switch on, pause a thing',
  'used_in_md': 'his rule 2026-10-13: the power button is the standard for every retire or deactivate',
  'never_md': 'delete (bin); stop (timer)'},
 {'slug': 'promote',
  'name': 'Promote',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-up-circle',
  'svg': '<path d="m15 11.25-3-3m0 0-3 3m3-3v7.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>',
  'aliases': 'move up',
  'used_in_md': 'his pick PR1',
  'never_md': 'upload'},
 {'slug': 'demote',
  'name': 'Demote',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-down-circle',
  'svg': '<path d="m9 12.75 3 3m0 0 3-3m-3 3v-7.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>',
  'aliases': 'move down',
  'used_in_md': 'his pick PR1',
  'never_md': 'download'},
 {'slug': 'sell',
  'name': 'Sell',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'shopping-cart',
  'svg': '<path d="M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 0 0-3 '
         '3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.924-7.138a60.114 60.114 0 0 0-16.536-1.84M7.5 14.25 '
         '5.106 5.272M6 20.25a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Zm12.75 0a.75.75 0 1 1-1.5 0 .75.75 0 0 1 '
         '1.5 0Z"/>',
  'aliases': 'sale, record a sale',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'recurring',
  'name': 'Recurring',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-path-rounded-square',
  'svg': '<path d="M19.5 12c0-1.232-.046-2.453-.138-3.662a4.006 4.006 0 0 0-3.7-3.7 48.678 48.678 0 0 '
         '0-7.324 0 4.006 4.006 0 0 0-3.7 3.7c-.017.22-.032.441-.046.662M19.5 12l3-3m-3 3-3-3m-12 3c0 '
         '1.232.046 2.453.138 3.662a4.006 4.006 0 0 0 3.7 3.7 48.656 48.656 0 0 0 7.324 0 4.006 4.006 0 0 0 '
         '3.7-3.7c.017-.22.032-.441.046-.662M4.5 12l3 3m-3-3-3 3"/>',
  'aliases': 'monthly fee, subscription',
  'used_in_md': '',
  'never_md': 'refresh (open arrows)'},
 {'slug': 'play',
  'name': 'Start',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'play',
  'svg': '<path d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 0 1 0 1.972l-11.54 '
         '6.347a1.125 1.125 0 0 1-1.667-.986V5.653Z"/>',
  'aliases': 'start timer',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'pause',
  'name': 'Pause',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'pause',
  'svg': '<path d="M15.75 5.25v13.5m-7.5-13.5v13.5"/>',
  'aliases': 'pause timer',
  'used_in_md': '',
  'never_md': 'power (switching a thing off)'},
 {'slug': 'stop',
  'name': 'Stop',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'stop',
  'svg': '<path d="M5.25 7.5A2.25 2.25 0 0 1 7.5 5.25h9a2.25 2.25 0 0 1 2.25 2.25v9a2.25 2.25 0 0 1-2.25 '
         '2.25h-9a2.25 2.25 0 0 1-2.25-2.25v-9Z"/>',
  'aliases': 'stop and save',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'drag',
  'name': 'Drag',
  'group': 'action',
  'library': 'Built by Bean',
  'icon_name': 'six-dot grip',
  'svg': '<circle cx="9" cy="6" r="1" fill="currentColor"/><circle cx="15" cy="6" r="1" '
         'fill="currentColor"/><circle cx="9" cy="12" r="1" fill="currentColor"/><circle cx="15" cy="12" '
         'r="1" fill="currentColor"/><circle cx="9" cy="18" r="1" fill="currentColor"/><circle cx="15" '
         'cy="18" r="1" fill="currentColor"/>',
  'aliases': 'grip, reorder, move',
  'used_in_md': 'BBB My Apps and Workspace task cards',
  'never_md': 'more (three dots)'},
 {'slug': 'prompt',
  'name': 'Prompt',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'command-line',
  'svg': '<path d="m6.75 7.5 3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0 0 21 18V6a2.25 2.25 0 0 '
         '0-2.25-2.25H5.25A2.25 2.25 0 0 0 3 6v12a2.25 2.25 0 0 0 2.25 2.25Z"/>',
  'aliases': 'build prompt, terminal',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'warning',
  'name': 'Warning',
  'group': 'status',
  'library': 'Heroicons outline',
  'icon_name': 'exclamation-triangle',
  'svg': '<path d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 '
         '1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"/>',
  'aliases': 'needs a look, caution',
  'used_in_md': 'EntertainHQ, BBB, Personal-Trainer, Data Dungeon, Piped',
  'never_md': 'reports (Data Dungeon drew Reports with a triangle)'},
 {'slug': 'error',
  'name': 'Problem',
  'group': 'status',
  'library': 'Heroicons outline',
  'icon_name': 'exclamation-circle',
  'svg': '<path d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z"/>',
  'aliases': 'error, missing, failed, will not close',
  'used_in_md': 'EntertainHQ, BBB, Personal-Trainer, Data Dungeon, Piped',
  'never_md': ''},
 {'slug': 'info',
  'name': 'Info',
  'group': 'status',
  'library': 'Heroicons outline',
  'icon_name': 'information-circle',
  'svg': '<path d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 '
         '1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z"/>',
  'aliases': 'about, note',
  'used_in_md': 'EntertainHQ, BBB, Personal-Trainer, Data Dungeon, Piped',
  'never_md': ''},
 {'slug': 'help',
  'name': 'Help',
  'group': 'status',
  'library': 'Heroicons outline',
  'icon_name': 'question-mark-circle',
  'svg': '<path d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 '
         '3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 '
         '0Zm-9 5.25h.008v.008H12v-.008Z"/>',
  'aliases': 'how to, hint',
  'used_in_md': 'EntertainHQ, BBB, Personal-Trainer, Data Dungeon, Piped',
  'never_md': 'support (the desk)'},
 {'slug': 'locked',
  'name': 'Locked',
  'group': 'status',
  'library': 'Heroicons outline',
  'icon_name': 'lock-closed',
  'svg': '<path d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 '
         '2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 '
         '2.25Z"/>',
  'aliases': 'private, phase locked, lock',
  'used_in_md': 'his pick LK1; EntertainHQ, BBB, Piped',
  'never_md': ''},
 {'slug': 'unlocked',
  'name': 'Unlocked',
  'group': 'status',
  'library': 'Heroicons outline',
  'icon_name': 'lock-open',
  'svg': '<path d="M13.5 10.5V6.75a4.5 4.5 0 1 1 9 0v3.75M3.75 21.75h10.5a2.25 2.25 0 0 0 '
         '2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H3.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 '
         '2.25Z"/>',
  'aliases': 'unlock, open to edit',
  'used_in_md': 'his pick LK1',
  'never_md': ''},
 {'slug': 'verify',
  'name': 'Verify',
  'group': 'status',
  'library': 'Heroicons outline',
  'icon_name': 'beaker',
  'svg': '<path d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 '
         '3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 '
         '1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 '
         '15a9.065 9.065 0 0 0-6.23-.693L5 14.5m14.8.8 1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 '
         '48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5"/>',
  'aliases': 'prove it works, test it, how to check',
  'used_in_md': '',
  'never_md': 'search; done; sign'},
 {'slug': 'trend-up',
  'name': 'Going up',
  'group': 'status',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-trending-up',
  'svg': '<path d="M2.25 18 9 11.25l4.306 4.306a11.95 11.95 0 0 1 5.814-5.518l2.74-1.22m0 0-5.94-2.281m5.94 '
         '2.28-2.28 5.941"/>',
  'aliases': 'growth, profit',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'trend-down',
  'name': 'Going down',
  'group': 'status',
  'library': 'Heroicons outline',
  'icon_name': 'arrow-trending-down',
  'svg': '<path d="M2.25 6 9 12.75l4.286-4.286a11.948 11.948 0 0 1 4.306 6.43l.776 2.898m0 0 '
         '3.182-5.511m-3.182 5.51-5.511-3.181"/>',
  'aliases': 'decline, loss',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'whats-new',
  'name': "What's new",
  'group': 'status',
  'library': 'Heroicons outline',
  'icon_name': 'sparkles',
  'svg': '<path d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 '
         '0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 '
         '3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 '
         '3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 '
         '3.375 0 0 0-2.456 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 '
         '18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 '
         '1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z"/>',
  'aliases': 'announcements, release notes',
  'used_in_md': 'EntertainHQ and Piped',
  'never_md': 'leads (megaphone); notifications (bell)'},
 {'slug': 'revenue',
  'name': 'Revenue',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'banknotes',
  'svg': '<path d="M2.25 18.75a60.07 60.07 0 0 1 15.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 '
         '4.5v.75A.75.75 0 0 1 3 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 '
         '.414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 '
         '1.125h-.375m1.5-1.5H21a.75.75 0 0 0-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 0 '
         '1-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 0 0 3 15h-.75M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm3 '
         '0h.008v.008H18V10.5Zm-12 0h.008v.008H6V10.5Z"/>',
  'aliases': 'income, money in, paid, balance',
  'used_in_md': '',
  'never_md': 'expenses (receipt); payments (card)'},
 {'slug': 'payments',
  'name': 'Payments',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'credit-card',
  'svg': '<path d="M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 0 0 '
         '2.25-2.25V6.75A2.25 2.25 0 0 0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25v10.5A2.25 2.25 0 0 0 4.5 '
         '19.5Z"/>',
  'aliases': 'card, pay, talent payments',
  'used_in_md': 'EntertainHQ and Piped',
  'never_md': 'expenses (receipt); books'},
 {'slug': 'vendors',
  'name': 'Vendors',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'building-storefront',
  'svg': '<path d="M13.5 21v-7.5a.75.75 0 0 1 .75-.75h3a.75.75 0 0 1 .75.75V21m-4.5 0H2.36m11.14 0H18m0 '
         '0h3.64m-1.39 0V9.349M3.75 21V9.349m0 0a3.001 3.001 0 0 0 3.75-.615A2.993 2.993 0 0 0 9.75 '
         '9.75c.896 0 1.7-.393 2.25-1.016a2.993 2.993 0 0 0 2.25 1.016c.896 0 1.7-.393 2.25-1.015a3.001 '
         '3.001 0 0 0 3.75.614m-16.5 0a3.004 3.004 0 0 1-.621-4.72l1.189-1.19A1.5 1.5 0 0 1 5.378 '
         '3h13.243a1.5 1.5 0 0 1 1.06.44l1.19 1.189a3 3 0 0 1-.621 4.72M6.75 18h3.75a.75.75 0 0 0 '
         '.75-.75V13.5a.75.75 0 0 0-.75-.75H6.75a.75.75 0 0 0-.75.75v3.75c0 .414.336.75.75.75Z"/>',
  'aliases': 'providers, suppliers, who charges us',
  'used_in_md': 'Kuper and Robinson draw a shop for a vendor',
  'never_md': 'hosting (servers)'},
 {'slug': 'mail',
  'name': 'Email',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'envelope',
  'svg': '<path d="M21.75 6.75v10.5a2.25 2.25 0 0 1-2.25 2.25h-15a2.25 2.25 0 0 1-2.25-2.25V6.75m19.5 0A2.25 '
         '2.25 0 0 0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25m19.5 0v.243a2.25 2.25 0 0 1-1.07 1.916l-7.5 '
         '4.615a2.25 2.25 0 0 1-2.36 0L3.32 8.91a2.25 2.25 0 0 1-1.07-1.916V6.75"/>',
  'aliases': 'mail, inbox of mail',
  'used_in_md': 'his pick EM1; six repos',
  'never_md': ''},
 {'slug': 'archive',
  'name': 'Archive',
  'group': 'action',
  'library': 'Heroicons outline',
  'icon_name': 'archive-box',
  'svg': '<path d="m20.25 7.5-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 '
         '7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 '
         '0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z"/>',
  'aliases': 'put away, file it, off the list',
  'used_in_md': 'the inbox, 2026-11-06 (issue #40)',
  'never_md': ''},
 {'slug': 'texting',
  'name': 'Texting',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'chat-bubble-oval-left-ellipsis',
  'svg': '<path d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 '
         '0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 '
         '12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 '
         '0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 '
         '12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z"/>',
  'aliases': 'SMS, text messages, text',
  'used_in_md': 'his pick TX1',
  'never_md': 'messages (team chat, two bubbles)'},
 {'slug': 'phone',
  'name': 'Phone',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'phone',
  'svg': '<path d="M2.25 6.75c0 8.284 6.716 15 15 15h2.25a2.25 2.25 0 0 0 '
         '2.25-2.25v-1.372c0-.516-.351-.966-.852-1.091l-4.423-1.106c-.44-.11-.902.055-1.173.417l-.97 '
         '1.293c-.282.376-.769.542-1.21.38a12.035 12.035 0 0 '
         '1-7.143-7.143c-.162-.441.004-.928.38-1.21l1.293-.97c.363-.271.527-.734.417-1.173L6.963 3.102a1.125 '
         '1.125 0 0 0-1.091-.852H4.5A2.25 2.25 0 0 0 2.25 4.5v2.25Z"/>',
  'aliases': 'call, telephone',
  'used_in_md': 'a handset in EntertainHQ, Personal-Trainer, Kuper and Piped',
  'never_md': 'phone app (a device)'},
 {'slug': 'document',
  'name': 'Document',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'document',
  'svg': '<path d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 '
         '7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 '
         '.621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"/>',
  'aliases': 'file, PDF',
  'used_in_md': 'BBB; Kuper, Piped and Robinson draw a file',
  'never_md': 'projects (folder)'},
 {'slug': 'image',
  'name': 'Photo',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'photo',
  'svg': '<path d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 '
         '2.25 0 0 1 3.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 '
         '0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 '
         '1.5Zm10.5-11.25h.008v.008h-.008V8.25Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z"/>',
  'aliases': 'image, logo, mark',
  'used_in_md': 'his pick PH2',
  'never_md': ''},
 {'slug': 'notes',
  'name': 'Notes',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'bars-3-bottom-left',
  'svg': '<path d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12"/>',
  'aliases': 'description, has notes',
  'used_in_md': '',
  'never_md': 'menu (three even lines)'},
 {'slug': 'website',
  'name': 'Website',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'globe-alt',
  'svg': '<path d="M12 21a9.004 9.004 0 0 0 8.716-6.747M12 21a9.004 9.004 0 0 1-8.716-6.747M12 21c2.485 0 '
         '4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 0 1 7.843 '
         '4.582M12 3a8.997 8.997 0 0 0-7.843 4.582m15.686 0A11.953 11.953 0 0 1 12 10.5c-2.998 '
         '0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0 1 21 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 '
         '17.919 0 0 1 12 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 0 1 3 12c0-1.605.42-3.113 '
         '1.157-4.418"/>',
  'aliases': 'site, domain, web',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'web-app',
  'name': 'Web app',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'window',
  'svg': '<path d="M3 8.25V18a2.25 2.25 0 0 0 2.25 2.25h13.5A2.25 2.25 0 0 0 21 18V8.25m-18 0V6a2.25 2.25 0 '
         '0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 6v2.25m-18 0h18M5.25 6h.008v.008H5.25V6ZM7.5 '
         '6h.008v.008H7.5V6Zm2.25 0h.008v.008H9.75V6Z"/>',
  'aliases': 'the app in a browser',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'phone-app',
  'name': 'Phone app',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'device-phone-mobile',
  'svg': '<path d="M10.5 1.5H8.25A2.25 2.25 0 0 0 6 3.75v16.5a2.25 2.25 0 0 0 2.25 2.25h7.5A2.25 2.25 0 0 0 '
         '18 20.25V3.75a2.25 2.25 0 0 0-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3m-3 18.75h3"/>',
  'aliases': 'iOS, Android, App Store, Play',
  'used_in_md': '',
  'never_md': 'phone (handset)'},
 {'slug': 'portal',
  'name': 'Portal',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'computer-desktop',
  'svg': '<path d="M9 17.25v1.007a3 3 0 0 1-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0 1 15 '
         '18.257V17.25m6-12V15a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 15V5.25m18 0A2.25 2.25 0 0 0 '
         '18.75 3H5.25A2.25 2.25 0 0 0 3 5.25m18 0V12a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 '
         '12V5.25"/>',
  'aliases': 'client portal, partner portal',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'admin-board',
  'name': 'Admin board',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'presentation-chart-line',
  'svg': '<path d="M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 '
         '0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 '
         '0-.5 1.5m.75-9 3-3 2.148 2.148A12.061 12.061 0 0 1 16.5 7.605"/>',
  'aliases': 'the board, back office',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'admin',
  'name': 'Admin',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'shield-check',
  'svg': '<path d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 '
         '9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 '
         '0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z"/>',
  'aliases': 'admin portal, roles, staff side',
  'used_in_md': 'EntertainHQ Users & Roles',
  'never_md': ''},
 {'slug': 'status-page',
  'name': 'Status page',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'signal',
  'svg': '<path d="M9.348 14.652a3.75 3.75 0 0 1 0-5.304m5.304 0a3.75 3.75 0 0 1 0 5.304m-7.425 2.121a6.75 '
         '6.75 0 0 1 0-9.546m9.546 0a6.75 6.75 0 0 1 0 9.546M5.106 18.894c-3.808-3.807-3.808-9.98 '
         '0-13.788m13.788 0c3.808 3.807 3.808 9.98 0 13.788M12 12h.008v.008H12V12Zm.375 0a.375.375 0 1 1-.75 '
         '0 .375.375 0 0 1 .75 0Z"/>',
  'aliases': 'uptime, outages',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'location',
  'name': 'Location',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'map-pin',
  'svg': '<path d="M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"/><path d="M19.5 10.5c0 7.142-7.5 11.25-7.5 '
         '11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1 1 15 0Z"/>',
  'aliases': 'address, place',
  'used_in_md': 'EntertainHQ',
  'never_md': 'business map'},
 {'slug': 'tag',
  'name': 'Tag',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'tag',
  'svg': '<path d="M9.568 3H5.25A2.25 2.25 0 0 0 3 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 '
         '1.78.872 2.607.33a18.095 18.095 0 0 0 5.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 '
         '2.25 0 0 0 9.568 3Z"/><path d="M6 6h.008v.008H6V6Z"/>',
  'aliases': 'label, category, price',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'star',
  'name': 'Star',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'star',
  'svg': '<path d="M11.48 3.499a.562.562 0 0 1 1.04 0l2.125 5.111a.563.563 0 0 0 '
         '.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 0 0-.182.557l1.285 '
         '5.385a.562.562 0 0 1-.84.61l-4.725-2.885a.562.562 0 0 0-.586 0L6.982 20.54a.562.562 0 0 '
         '1-.84-.61l1.285-5.386a.562.562 0 0 0-.182-.557l-4.204-3.602a.562.562 0 0 1 '
         '.321-.988l5.518-.442a.563.563 0 0 0 .475-.345L11.48 3.5Z"/>',
  'aliases': 'favourite, talent, rating',
  'used_in_md': 'EntertainHQ talent',
  'never_md': ''},
 {'slug': 'key',
  'name': 'Key',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'key',
  'svg': '<path d="M15.75 5.25a3 3 0 0 1 3 3m3 0a6 6 0 0 1-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 '
         '17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 '
         '.43-1.563A6 6 0 1 1 21.75 8.25Z"/>',
  'aliases': 'API key, token, reset password, access',
  'used_in_md': 'his pick K1',
  'never_md': ''},
 {'slug': 'code',
  'name': 'Code',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'code-bracket',
  'svg': '<path d="M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5"/>',
  'aliases': 'custom software, repo',
  'used_in_md': '',
  'never_md': ''},
 {'slug': 'package',
  'name': 'Package',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'cube',
  'svg': '<path d="m21 7.5-9-5.25L3 7.5m18 0-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9"/>',
  'aliases': 'bundle, boxes, inventory',
  'used_in_md': 'BBB price list and Piped packs',
  'never_md': ''},
 {'slug': 'steps',
  'name': 'Steps',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'numbered-list',
  'svg': '<path d="M8.242 5.992h12m-12 6.003H20.24m-12 5.999h12M4.117 7.495v-3.75H2.99m1.125 3.75H2.99m1.125 '
         '0H5.24m-1.92 2.577a1.125 1.125 0 1 1 1.591 1.59l-1.83 1.83h2.16M2.99 15.745h1.125a1.125 1.125 0 0 '
         '1 0 2.25H3.74m0-.002h.375a1.125 1.125 0 0 1 0 2.25H2.99"/>',
  'aliases': 'your steps, checklist in order',
  'used_in_md': '',
  'never_md': 'workspace and its tasks (inbox)'},
 {'slug': 'theme-light',
  'name': 'Light mode',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'sun',
  'svg': '<path d="M12 3v2.25m6.364.386-1.591 1.591M21 12h-2.25m-.386 6.364-1.591-1.591M12 '
         '18.75V21m-4.773-4.227-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 1 1-7.5 0 '
         '3.75 3.75 0 0 1 7.5 0Z"/>',
  'aliases': 'light',
  'used_in_md': 'Personal-Trainer, EntertainHQ, Piped site',
  'never_md': ''},
 {'slug': 'theme-dark',
  'name': 'Dark mode',
  'group': 'thing',
  'library': 'Heroicons outline',
  'icon_name': 'moon',
  'svg': '<path d="M21.752 15.002A9.72 9.72 0 0 1 18 15.75c-5.385 0-9.75-4.365-9.75-9.75 '
         '0-1.33.266-2.597.748-3.752A9.753 9.753 0 0 0 3 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 0 0 '
         '9.002-5.998Z"/>',
  'aliases': 'dark',
  'used_in_md': 'Personal-Trainer, EntertainHQ, Piped site',
  'never_md': ''}]
