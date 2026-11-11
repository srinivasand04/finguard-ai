"""Synthetic compliance corpus.

FinGuard Bank is fictional. Its internal policies below are invented for this
learning project. The two "study notes" documents paraphrase widely known public
FATF / EU AML concepts in our own words - they are NOT official texts or legal
advice. Real documents (e.g. official FATF PDFs) can be dropped into documents/
and are ingested the same way.

Each document is written to a different file format (PDF, DOCX, TXT, MD) so the
extraction layer is exercised end to end.
"""
from __future__ import annotations

from pathlib import Path

DISCLAIMER = ("Synthetic document for the FinGuard AI learning project. FinGuard Bank is fictional; "
              "this is not legal or regulatory advice.")

DOCS: list[dict] = [
    {
        "file": "aml_policies/finguard_aml_policy.pdf", "doc_type": "AML_POLICY",
        "title": "FinGuard Bank Anti-Money Laundering Policy",
        "sections": [
            ("1 Purpose and scope",
             "This policy sets out how FinGuard Bank prevents its products from being used for money laundering "
             "and terrorist financing. It applies to all business lines, all employees, contractors and outsourced "
             "service providers acting on behalf of the bank, in every country where the bank operates."),
            ("2 Roles and responsibilities",
             "The Management Board holds overall accountability for the AML framework and approves this policy at "
             "least once every 12 months. The Money Laundering Reporting Officer (MLRO) is responsible for "
             "suspicious activity reporting to the Financial Intelligence Unit and reports to the Board quarterly. "
             "The first line of defence (business units) owns customer due diligence; the second line (Compliance) "
             "sets standards and monitors; the third line (Internal Audit) reviews the AML framework at least every "
             "two years."),
            ("3 Risk-based approach",
             "The bank performs an enterprise-wide money laundering risk assessment every year, covering customers, "
             "products, delivery channels and geographies. Customers are rated LOW, MEDIUM or HIGH risk. Controls "
             "are proportionate to risk: higher-risk relationships receive enhanced due diligence and more frequent "
             "monitoring, while simplified due diligence may only be applied to low-risk relationships that meet the "
             "criteria in the KYC procedure."),
            ("4 Prohibited relationships",
             "The bank must not open or maintain anonymous accounts, accounts in obviously fictitious names, or "
             "relationships with shell banks. Relationships with persons on applicable sanctions lists are prohibited "
             "unless a licence has been granted by the competent authority and approved by the MLRO."),
            ("5 Transaction monitoring",
             "All customer transactions are subject to automated monitoring combining rules, machine-learning risk "
             "scores and network analytics. Model outputs are indicators that prioritise human review; an alert or "
             "score alone is never treated as proof of money laundering. Alert handling standards are defined in the "
             "Transaction Monitoring and Alert Handling Guideline."),
            ("6 Suspicious activity reporting",
             "Any employee who knows or suspects money laundering must report it internally to the MLRO without "
             "delay and in any case within 1 business day. The MLRO decides whether to file a Suspicious Activity "
             "Report (SAR) with the Financial Intelligence Unit. Employees must never inform the customer or any "
             "third party that a report has been made or is being considered (tipping-off prohibition)."),
            ("7 Record keeping",
             "Customer due diligence documents and transaction records are retained for at least 5 years after the "
             "end of the business relationship or the date of an occasional transaction. Records of internal "
             "investigations and SAR decisions are retained for the same period."),
            ("8 Training",
             "All staff complete AML training when they join and annually thereafter. Staff in high-risk roles, such "
             "as payments operations, correspondent banking and private banking, complete additional role-specific "
             "training every 6 months."),
            ("9 Model governance",
             "Detection models used for monitoring are registered with a version, training data description and "
             "evaluation metrics. Models are re-validated at least annually or after a material change in data or "
             "performance. Explanations of individual scores must be available to investigators."),
        ],
    },
    {
        "file": "kyc_policies/finguard_kyc_cdd_procedure.docx", "doc_type": "KYC_POLICY",
        "title": "FinGuard Bank KYC and Customer Due Diligence Procedure",
        "sections": [
            ("1 When customer due diligence is required",
             "Customer due diligence (CDD) must be completed before establishing a business relationship, before "
             "carrying out an occasional transaction of EUR 15,000 or more (whether in one operation or several "
             "linked operations), for any occasional wire transfer above EUR 1,000, whenever there is a suspicion of "
             "money laundering, and whenever there are doubts about previously obtained identification data."),
            ("2 Identification and verification of individuals",
             "For natural persons the bank collects full name, date of birth, nationality and residential address, "
             "and verifies identity using a valid government-issued photo identity document. Remote onboarding "
             "requires certified electronic identification or video identification with liveness detection."),
            ("3 Legal entities and beneficial owners",
             "For legal entities the bank obtains the registered name, registration number, registered address, "
             "legal form, directors and proof of existence from an official register. The bank identifies every "
             "beneficial owner holding more than 25% of shares or voting rights, or otherwise exercising control. "
             "Where no such person can be identified, the senior managing official is recorded as beneficial owner "
             "and the reason is documented."),
            ("4 Purpose and intended nature of the relationship",
             "Relationship managers record the purpose of the account, expected monthly transaction volumes, "
             "expected counterparties and countries, and the source of funds. These expectations form the "
             "behavioural baseline against which monitoring detects unusual activity."),
            ("5 Customer risk rating",
             "Every customer receives a risk rating at onboarding based on customer type, occupation or industry, "
             "geography, products, delivery channel and PEP status. Customers connected to elevated-risk "
             "jurisdictions, cash-intensive businesses or complex ownership structures start at MEDIUM risk or higher."),
            ("6 Simplified due diligence",
             "Simplified due diligence may be applied only to customers rated LOW risk, such as listed companies "
             "subject to disclosure requirements or public authorities. Simplified measures reduce the extent of "
             "verification but never remove ongoing monitoring."),
            ("7 Periodic review",
             "KYC files are reviewed periodically according to risk: HIGH-risk customers every 12 months, "
             "MEDIUM-risk customers every 24 months, and LOW-risk customers every 36 months. A trigger event, such "
             "as a material change in ownership, an adverse media hit or a confirmed suspicious alert, requires an "
             "immediate review regardless of the schedule."),
            ("8 Inability to complete CDD",
             "If CDD cannot be completed, the bank must not open the account or carry out the transaction, must "
             "consider terminating an existing relationship and must consider filing a suspicious activity report."),
        ],
    },
    {
        "file": "kyc_policies/finguard_edd_standard.pdf", "doc_type": "EDD_POLICY",
        "title": "FinGuard Bank Enhanced Due Diligence Standard",
        "sections": [
            ("1 When enhanced due diligence applies",
             "Enhanced due diligence (EDD) is mandatory for HIGH-risk customers, politically exposed persons (PEPs) "
             "and their family members and close associates, customers established in high-risk third countries "
             "identified by the authorities, cross-border correspondent relationships, and complex or unusually "
             "large transactions without an apparent economic or lawful purpose."),
            ("2 Politically exposed persons",
             "A PEP relationship may only be established or continued with the approval of senior management. The "
             "bank must establish the source of wealth and source of funds and conduct enhanced ongoing monitoring. "
             "A person who has left a prominent public function remains treated as a PEP for at least 12 months, "
             "and longer if the risk assessment requires it."),
            ("3 Enhanced measures",
             "EDD measures include obtaining additional information on the customer and beneficial owners, "
             "corroborating source of funds and source of wealth with documentary evidence, obtaining senior "
             "management approval, and increasing the number and frequency of controls, including manual review of "
             "selected transactions."),
            ("4 High-risk jurisdictions",
             "Transactions with counterparties in elevated-risk jurisdictions require documented business rationale. "
             "Wire transfers above EUR 10,000 to or from such jurisdictions are reviewed by Compliance before or "
             "promptly after execution, depending on the product."),
            ("5 Approval and review",
             "EDD files are approved by a senior manager independent of the relationship manager and reviewed at "
             "least every 12 months. Exits from EDD relationships are documented and assessed for reporting."),
        ],
    },
    {
        "file": "aml_policies/transaction_monitoring_guideline.docx", "doc_type": "TRANSACTION_MONITORING",
        "title": "FinGuard Bank Transaction Monitoring and Alert Handling Guideline",
        "sections": [
            ("1 Monitoring sources",
             "Alerts are generated by four independent sources: supervised machine-learning risk scores, unsupervised "
             "anomaly detection, deterministic rules (for example structuring), and graph analytics that identify "
             "circular flows, layering chains and suspicious networks of accounts."),
            ("2 Alert prioritisation",
             "Alerts are prioritised by severity. CRITICAL alerts must be reviewed within 1 business day, HIGH alerts "
             "within 3 business days and MEDIUM alerts within 10 business days. Severity is derived from the risk "
             "score but analysts may escalate any alert based on context."),
            ("3 Level 1 review",
             "The Level 1 analyst reviews the alert reasons, the customer profile, expected behaviour recorded at "
             "onboarding, recent transactions and counterparties. The analyst either closes the alert as a false "
             "positive with a documented rationale or escalates it to a Level 2 investigation."),
            ("4 Level 2 investigation",
             "Level 2 investigators analyse the wider network of connected accounts, request information from the "
             "relationship manager or customer where appropriate (without tipping off), and prepare an investigation "
             "summary with evidence references. The case is then proposed for closure or for SAR consideration by "
             "the MLRO."),
            ("5 Structuring indicators",
             "Structuring is the splitting of transactions to stay below reporting or monitoring thresholds. Three or "
             "more transactions between EUR 9,000 and EUR 10,000 from the same account within 7 days must generate a "
             "structuring alert. Analysts should also consider deposits split across several accounts or branches."),
            ("6 Network and layering indicators",
             "Typical laundering typologies include fan-in (many senders funnelling to one account), fan-out (one "
             "account distributing to many), round-tripping where funds return to the originator through "
             "intermediaries, and layering chains where funds pass rapidly through several accounts while keeping "
             "most of their value. Money that leaves an account within 72 hours of arriving, at a similar amount, is a "
             "pass-through indicator."),
            ("7 Use of model outputs",
             "Risk scores, anomaly percentiles and network findings are investigative indicators. Investigators must "
             "verify them against underlying transaction records and must never close or escalate a case solely "
             "because of a score. Overrides of model recommendations are recorded with a reason."),
            ("8 Quality assurance",
             "Compliance quality assurance samples at least 5% of closed alerts every month to verify that closure "
             "rationales are adequate. Monitoring rule thresholds and model performance are tuned at least annually."),
        ],
    },
    {
        "file": "aml_policies/sanctions_screening_procedure.txt", "doc_type": "SANCTIONS",
        "title": "FinGuard Bank Sanctions Screening Procedure",
        "sections": [
            ("1 Lists screened",
             "The bank screens customers, beneficial owners and payment parties against the consolidated EU "
             "financial sanctions list, the UN Security Council consolidated list and any additional lists required "
             "by the jurisdictions in which the bank operates."),
            ("2 Customer screening",
             "Customers and beneficial owners are screened at onboarding and re-screened daily against list updates. "
             "Onboarding cannot be completed while a potential match is unresolved."),
            ("3 Payment screening",
             "All incoming and outgoing cross-border payments are screened in real time before execution. A payment "
             "with a potential match is held until the alert is resolved."),
            ("4 Handling potential matches",
             "Potential matches are reviewed by the sanctions team within 4 business hours. False positives are "
             "closed with a documented reason. Confirmed matches result in freezing of funds and a report to the "
             "competent national authority without delay; the customer must not be informed in a way that "
             "prejudices the report."),
            ("5 Escalation",
             "Confirmed matches, and any case where funds may have been made available to a designated person, are "
             "escalated immediately to the Head of Compliance and the MLRO."),
        ],
    },
    {
        "file": "investigation_templates/investigation_and_sar_procedure.pdf", "doc_type": "INVESTIGATION_PROCEDURE",
        "title": "FinGuard Bank Financial Crime Investigation and SAR Escalation Procedure",
        "sections": [
            ("1 Opening a case",
             "An investigation case is opened when a Level 1 analyst escalates an alert, when several alerts relate to "
             "the same customer or network, or on referral from another department. Each case receives a unique "
             "reference and an owner."),
            ("2 Evidence standards",
             "Every finding in an investigation must reference its supporting evidence: transaction identifiers, "
             "customer and account identifiers, model version and score, graph pattern or network identifiers, and "
             "the policy sections relied upon. AI-generated observations must be labelled as such and verified by the "
             "investigator."),
            ("3 Investigation report contents",
             "The investigation report contains: a summary, customer information, suspicious transaction patterns, "
             "machine-learning findings, graph analysis, compliance references, supporting evidence, recommended "
             "next steps, the human reviewer decision and the final case status."),
            ("4 Decision and approval",
             "Investigation outcomes are proposed by the investigator and approved by an Investigation Manager. "
             "Possible decisions are: close with no further action, request additional investigation, escalate to the "
             "MLRO for SAR consideration, or recommend relationship exit. The four-eyes principle applies to every "
             "closure of a case that contained a HIGH or CRITICAL alert."),
            ("5 SAR filing timeline",
             "When the MLRO decides that a report is required, the SAR is filed with the Financial Intelligence Unit "
             "within 5 business days of that decision. If a transaction is still pending and suspicion exists, the "
             "bank should refrain from executing it until it has informed the FIU, where the law permits."),
            ("6 Case closure and retention",
             "Closed cases record the decision, approver, date and rationale. Case files, including evidence and AI "
             "execution traces, are retained for 5 years."),
        ],
    },
    {
        "file": "aml_policies/fatf_recommendations_study_notes.md", "doc_type": "FATF_SUMMARY",
        "title": "FATF Recommendations - Study Notes (paraphrased)",
        "sections": [
            ("1 About the FATF",
             "The Financial Action Task Force (FATF) is an inter-governmental body that sets international standards "
             "to combat money laundering, terrorist financing and proliferation financing. Its standards are the 40 "
             "FATF Recommendations, and countries are assessed on them through mutual evaluations. These notes "
             "paraphrase key ideas for study purposes only; consult the official FATF text for authoritative wording."),
            ("2 Risk-based approach (Recommendation 1)",
             "Countries and financial institutions should identify, assess and understand their money laundering and "
             "terrorist financing risks and apply measures proportionate to those risks, with enhanced measures where "
             "risks are higher."),
            ("3 Customer due diligence (Recommendation 10)",
             "Financial institutions should not keep anonymous accounts. They should identify and verify customers and "
             "beneficial owners, understand the purpose of the relationship, and conduct ongoing due diligence. The "
             "FATF standard includes a designated threshold of USD/EUR 15,000 for occasional transactions."),
            ("4 Record keeping (Recommendation 11)",
             "Records of transactions and CDD information should be kept for at least five years so that they can be "
             "provided swiftly to competent authorities."),
            ("5 Politically exposed persons (Recommendation 12)",
             "For foreign PEPs, institutions should have risk management systems to identify them, obtain senior "
             "management approval, establish source of wealth and source of funds, and conduct enhanced ongoing "
             "monitoring. Domestic PEPs require these measures when the relationship is higher risk."),
            ("6 Wire transfers (Recommendation 16)",
             "Wire transfers should carry accurate originator and beneficiary information throughout the payment chain "
             "so that transfers can be traced. A de minimis threshold of USD/EUR 1,000 may be applied for reduced "
             "information requirements."),
            ("7 Suspicious transaction reporting (Recommendation 20)",
             "If a financial institution suspects or has reasonable grounds to suspect that funds are the proceeds of "
             "crime or related to terrorist financing, it should report promptly to the Financial Intelligence Unit."),
            ("8 Tipping-off and confidentiality (Recommendation 21)",
             "Institutions and their staff should be protected when reporting in good faith and should be prohibited "
             "from disclosing that a suspicious transaction report is being filed."),
            ("9 Beneficial ownership (Recommendations 24 and 25)",
             "Countries should ensure adequate, accurate and up-to-date information on the beneficial ownership of "
             "legal persons and legal arrangements is available to competent authorities in a timely manner."),
        ],
    },
    {
        "file": "aml_policies/eu_aml_framework_study_notes.md", "doc_type": "EU_AML",
        "title": "EU Anti-Money Laundering Framework - Study Notes (paraphrased)",
        "sections": [
            ("1 Overview",
             "The EU framework has evolved through successive AML Directives. In 2024 the EU adopted a package that "
             "includes a directly applicable AML Regulation (Regulation (EU) 2024/1624), a sixth AML Directive and a "
             "regulation creating a new EU Anti-Money Laundering Authority (AMLA) based in Frankfurt. Most of the "
             "single rulebook obligations apply from July 2027. These notes are a study summary, not legal text."),
            ("2 Customer due diligence thresholds",
             "Obliged entities apply CDD when establishing a business relationship and for occasional transactions of "
             "EUR 15,000 or more, and for occasional transfers of funds above EUR 1,000. The Funds Transfer Regulation "
             "requires information on payer and payee to accompany transfers of funds."),
            ("3 Beneficial ownership",
             "A beneficial owner of a legal entity is generally a natural person who ultimately owns or controls it, "
             "with ownership of more than 25% of shares or voting rights as an indication. Member States maintain "
             "central beneficial ownership registers."),
            ("4 Cash limit",
             "The AML Regulation introduces an EU-wide limit of EUR 10,000 on cash payments for goods or services by "
             "traders, with Member States able to set lower limits."),
            ("5 High-risk third countries",
             "The European Commission identifies high-risk third countries with strategic deficiencies in their AML "
             "regimes. Obliged entities must apply enhanced due diligence to business relationships and transactions "
             "involving those countries."),
            ("6 Role of AMLA",
             "AMLA coordinates national supervisors and financial intelligence units and will directly supervise a "
             "limited number of the highest-risk cross-border financial institutions."),
        ],
    },
]


def write_corpus(root: Path) -> list[Path]:
    """Render every document into its file format under `root`. Returns written paths."""
    written = []
    for d in DOCS:
        path = root / d["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        ext = path.suffix.lower()
        if ext == ".pdf":
            _write_pdf(path, d)
        elif ext == ".docx":
            _write_docx(path, d)
        elif ext == ".md":
            body = [f"# {d['title']}", "", f"_{DISCLAIMER}_", ""]
            for h, txt in d["sections"]:
                body += [f"## {h}", "", txt, ""]
            path.write_text("\n".join(body), encoding="utf-8")
        else:  # .txt: numbered headings in capitals
            body = [d["title"].upper(), DISCLAIMER, ""]
            for h, txt in d["sections"]:
                body += [h.upper(), txt, ""]
            path.write_text("\n".join(body), encoding="utf-8")
        written.append(path)
    return written


def _write_pdf(path: Path, d: dict) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    story = [Paragraph(d["title"], styles["Title"]), Paragraph(DISCLAIMER, styles["Italic"]), Spacer(1, 12)]
    for i, (h, txt) in enumerate(d["sections"]):
        if i and i % 3 == 0:          # spread sections over several pages so page citations are meaningful
            story.append(PageBreak())
        story += [Paragraph(h, styles["Heading2"]), Paragraph(txt, styles["BodyText"]), Spacer(1, 8)]
    SimpleDocTemplate(str(path), pagesize=A4, title=d["title"]).build(story)


def _write_docx(path: Path, d: dict) -> None:
    import docx

    doc = docx.Document()
    doc.core_properties.title = d["title"]
    doc.add_heading(d["title"], level=0)
    doc.add_paragraph().add_run(DISCLAIMER).italic = True
    for h, txt in d["sections"]:
        doc.add_heading(h, level=1)
        doc.add_paragraph(txt)
    doc.save(str(path))


def doc_type_for(path: Path) -> tuple[str, str | None]:
    """Known corpus documents get their declared type/title; anything else is classified by folder."""
    for d in DOCS:
        if path.as_posix().endswith(d["file"]):
            return d["doc_type"], d["title"]
    folder = path.parent.name.lower()
    return {"aml_policies": "AML_POLICY", "kyc_policies": "KYC_POLICY",
            "investigation_templates": "INVESTIGATION_PROCEDURE"}.get(folder, "OTHER"), None
