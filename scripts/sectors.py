"""Rough sector sort for payers. Edit freely: the first rule that matches wins.

OVR fixes single payers by their tidied name (lower case, no Ltd/plc/the).
"""
import re

RULES=[
 ('Foreign governments',r'embassy|ministry|government|prime minister|parliament of|house of representatives|federal department|high commission|consulate|state of qatar|kingdom|republic|ambassador|riyadh season|national assembly|knesset|bundestag|mofa|foreign affairs'),
 ('Gambling',r'betting|gaming|bet365|paddy power|flutter|entain|william hill|ladbrokes|sky bet|casino|lottery|camelot|allwyn|gambl'),
 ('Unions',r'union|unison|unite\b|gmb|usdaw|nasuwt|\bneu\b|rmt|aslef|\bcwu\b|\bpcs\b|\bfbu\b|tssa|bectu|prospect|community trade|nurses|\bbma\b|tulo|fire brigades'),
 ('Farming, food & drink',r'\bfarms?\b|farming|farmers\b|agricultur|arable|\bnfu\b|\bfood\b|\bdrinks?\b|\bbeer\b|brew|\bpubs?\b|whisky|\bwine|spirits|soft drinks?|dairy|\bmeat|poultry|\bfish|salmon|seafood|bakery|restaurant|catering|\btesco|sainsbury.s supermarket|co-operative group|\brabi\b|grocer|supermarket|mcdonald|nestl|diageo|coca-cola|pepsi|cranswick|moy park|\bsugar'),
 ('Finance & investment',r'bank|capital|invest|asset|fund|financ|goldman|blackrock|hsbc|barclays|lloyds|natwest|private equity|venture|wealth|pension|insur|broker|trading|bullion|hedge|partners lp|securities|brevan|caxton|man group|man capital|reit|equity|credit|payments|fintech|stock'),
 ('Tech & AI',r'microsoft|google|meta|amazon|apple|anthropic|openai|x corp|tiktok|bytedance|software|tech|digital|\bai\b|data|cyber|quantum|semiconductor|telecom|mobile|bt group|vodafone|cameo|baron app|online|internet|computing|coforge|multiverse|slalom|palantir'),
 ('Media & publishing',r'news|media|times|telegraph|guardian|mail|express|mirror|spectator|economist|publish|random house|penguin|harper|books|bbc|itv|itn|sky|channel|radio|podcast|journal|magazine|post\b|literary|agent|tv|television|press|writers|conville|united agents|independent'),
 ('Sport & racing',r'football|premier league|cricket|rugby|tennis|\blta\b|golf|racecourse|jockey|racing|ascot|epsom|silverstone|formula|f1|boxing|darts|olympic|athletic|sport|wimbledon|wembley|great north run|stadium|cricket club|football club'),
 ('Law',r'law|legal|solicitor|chambers|barrister|withers|travers|attorney|court|justice|counsel'),
 ('Energy & industry',r'energy|oil|gas|petrol|bp\b|shell|nuclear|power|electric|renewable|wind|solar|mining|steel|aluminium|bamford|jcb|manufactur|industr|engineering|reliance|chemicals|aerospace|motor|automotive|refrigeration|construction|infrastructure'),
 ('Defence & security',r'defence|defense|armed forces|military|naval|army|raf\b|security|bae|thales|lockheed|qinetiq|weapon'),
 ('Property',r'property|properties|estate|homes|housing|developments|land\b|real estate|lettings'),
 ('Health & pharma',r'health|pharma|medical|clinic|hospital|nhs|astrazeneca|gsk|pfizer|vaccine|care\b|dental|\bbio'),
 ('Arts, music & events',r'music|bpi|festival|theatre|opera|arts|gallery|museum|concert|prize|film|cinema|entertainment|events'),
 ('Think tanks, campaigns & lobby groups',r'friends of|institute|institution|foundation|forum|council|centre|center|coalition|alliance|campaign|association|society|trust|policy|project|initiative|movement|best for britain|compass|stiftung|elnet|parliamentary group|appg|all-party|club|charity|relief|university|college|school|academy|commission|federation|chamber'),
]
OVR={'national farmers union':'Farming, food & drink','lord michael farmer':'Private individuals','national liberal club':'Think tanks, campaigns & lobby groups','august':'Think tanks, campaigns & lobby groups','opd group':'Energy & industry','ipsa':'Other / unsorted','ecotricity group':'Energy & industry','tattersalls':'Sport & racing','trailfinders':'Other / unsorted','ernst & young llp':'Finance & investment','ey':'Finance & investment','reach group':'Media & publishing','informa':'Media & publishing','head of zeus uk':'Media & publishing','bpp holdings':'Other / unsorted','89up':'Think tanks, campaigns & lobby groups','thinklabour':'Think tanks, campaigns & lobby groups','london borough of sutton':'Other / unsorted'}


def sector(pkey, payer, payer_type, cat):
    if pkey in OVR:
        return OVR[pkey]
    t = " ".join(str(x) for x in (payer, payer_type) if x and str(x) != "nan").lower()
    for name, rx in RULES:
        if re.search(rx, t):
            return name
    pt = str(payer_type or "").lower()
    if "individual" in pt:
        return "Private individuals"
    if cat == "2" and pt in ("", "nan"):
        return "Private individuals"
    return "Other / unsorted"
