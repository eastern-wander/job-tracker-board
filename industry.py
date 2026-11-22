import re

CRYPTO = r"web[ -]?3|blockchain|crypto(?:currency)?|defi|decentralized finance|nfts?|daos?|tokeni[sz]\w*|token(?:s|omics)?|digital assets?|on[ -]?chain|gamefi|stablecoins?"
CORE = r"exchange|brokerage|wallets?|protocol|infrastructure|analytics|gaming|trading|platform|ecosystem|projects?|marketplace"
KNOWN = {"apex protocol", "bybit", "coinbase", "binance", "kraken", "okx", "orderly", "orderly network", "decibel foundation", "daos hub"}
TRADITIONAL = r"commercial banking|traditional bank(?:ing)?|commodity trading|oil (?:and|&) gas|shipping|logistics|saas|enterprise software|e-commerce|ecommerce|consulting|traditional brokerage|artificial intelligence"


def classify(job):
    company = re.sub(r"[^a-z0-9 ]", " ", job.get("company", "").lower())
    company = " ".join(company.split())
    title = job.get("title", "").lower()
    jd = (job.get("jd") or "").lower()
    declared = job.get("industry_declared")
    domain = re.search(r"\b(?:web[ -]?3|defi|gamefi|crypto(?:currency)?|nfts?|daos?)\b|\b(?:" +
                       CRYPTO + r")\s+(?:" + CORE + r")\b", title)
    primary = re.search(r"\b(?:we are|our (?:core )?(?:business|platform) is|company is)\b[^.\n]{0,100}\b(?:" +
                        CRYPTO + r")\b[^.\n]{0,45}\b(?:" + CORE + r")\b", jd)
    responsibility = re.search(r"\b(?:build|develop|manage|operate|lead|design)\b[^.\n]{0,65}\b(?:" +
                               CRYPTO + r")\b\s+(?:" + CORE + r")\b", jd)
    if declared == "web3" or company in KNOWN or domain or primary or responsibility:
        return {"state": "excluded", "reason": "Web3/Crypto is the employer's primary business or a core responsibility of this role."}
    sector = re.search(r"\b(?:" + TRADITIONAL + r")\b", title + " " + jd)
    if declared == "traditional" or sector:
        return {"state": "allowed", "category": sector[0].title() if sector else "Traditional industry",
                "reason": "Traditional industry; no primary Web3/Crypto scope identified."}
    return {"state": "review", "reason": "Primary industry unclear. Verify employer business and role responsibilities."}


def require_allowed(job):
    result = classify(job)
    if result["state"] != "allowed":
        raise ValueError(result["reason"])
