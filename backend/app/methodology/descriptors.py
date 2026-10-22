"""Official 1–5 descriptors for every AIRA-DDA-1.0 scoring sub-factor.

These are display/audit metadata. They do not affect the numeric formulas.
"""

from __future__ import annotations

IMPACT_DESCRIPTORS = {
    "Business Criticality": {
        1: "Experimental, discretionary or non-critical activity; no material dependency.",
        2: "Supports a non-critical activity; interruption causes limited inconvenience.",
        3: "Supports an important process; failure requires management intervention or workaround.",
        4: "Supports a high-value or critical process; failure materially affects service or business outcomes.",
        5: "Business-critical or mission-critical use; failure could cause sustained or enterprise-level disruption.",
    },
    "Customer / Service Impact": {
        1: "No customer-facing effect or negligible service impact.",
        2: "Small number of customers affected; short-lived and easily corrected impact.",
        3: "Noticeable customer/service degradation affecting a meaningful population; generally reversible.",
        4: "Significant service degradation, incorrect customer outcomes, or material customer harm.",
        5: "Widespread or severe customer impact, prolonged service loss, or potentially irreversible harm.",
    },
    "Decision Consequence": {
        1: "AI output is advisory only and has no meaningful effect on decisions.",
        2: "Supports low-consequence decisions with simple human correction.",
        3: "Influences material operational or business decisions requiring review.",
        4: "Materially influences high-consequence decisions affecting customers, employees, revenue or operations.",
        5: "Directly determines highly consequential or rights-/service-critical decisions with limited opportunity for correction.",
    },
    "Operational Dependency": {
        1: "No operational dependency; manual alternative is readily available.",
        2: "Limited dependency; simple fallback exists with minimal disruption.",
        3: "Moderate dependency; fallback requires effort, delay or management intervention.",
        4: "High dependency; failure disrupts important workflows and fallback capacity is constrained.",
        5: "Critical dependency; AI failure could halt or materially impair essential operations.",
    },
    "Financial Exposure": {
        1: "Negligible financial effect.",
        2: "Limited cost, loss or revenue impact that can be absorbed within routine operations.",
        3: "Material but manageable financial exposure requiring management action.",
        4: "Significant loss, revenue impact, liability or remediation cost.",
        5: "Severe or enterprise-significant financial loss, liability, penalty or sustained revenue impact.",
    },
    "Resilience / Continuity": {
        1: "No meaningful resilience or continuity impact.",
        2: "Minor disruption with rapid recovery and established workaround.",
        3: "Moderate disruption requiring recovery procedures or temporary service degradation.",
        4: "Significant continuity impact; recovery is complex, delayed or dependent on scarce resources.",
        5: "Failure could cause prolonged outage, systemic disruption or inability to deliver critical services.",
    },
    "Third-Party / Supplier Dependency": {
        1: "No material third-party dependency or easily substitutable supplier.",
        2: "Low dependency with alternative suppliers or simple exit options.",
        3: "Meaningful dependency; switching or remediation requires time and coordination.",
        4: "High dependency on a key supplier, proprietary model, platform or service.",
        5: "Critical concentration or lock-in; supplier failure, withdrawal or restriction could materially impair the use case.",
    },
    "Strategic / Sovereignty Dependency": {
        1: "No material strategic, jurisdictional or sovereignty dependency.",
        2: "Limited external dependency with low sensitivity and practical alternatives.",
        3: "Meaningful dependency on external technology, jurisdiction, data location or strategic supplier.",
        4: "Significant dependency affecting data control, technology autonomy, regulatory posture or strategic resilience.",
        5: "Critical sovereignty exposure, including unacceptable external control, jurisdictional dependence, restricted data/model control or inability to operate independently.",
    },
    "Population Affected": {
        1: "Very few or no identifiable individuals affected.",
        2: "Small, contained population.",
        3: "Moderate population or recurring impact across a business/customer segment.",
        4: "Large population or broad customer/employee exposure.",
        5: "Very large, enterprise-wide or societal-scale population affected.",
    },
    "Vulnerable / Higher-Impact Groups": {
        1: "No vulnerable or higher-impact group is reasonably affected.",
        2: "Limited indirect exposure with negligible differentiated harm.",
        3: "A vulnerable or higher-impact group may be affected, but impacts are generally reversible and mitigable.",
        4: "Material impact on vulnerable or higher-impact groups requiring enhanced safeguards.",
        5: "Severe, disproportionate or potentially irreversible impact on vulnerable or protected groups.",
    },
    "Employee Impact": {
        1: "No meaningful employee impact.",
        2: "Minor administrative or productivity impact with easy correction.",
        3: "Material effect on work allocation, performance, access, monitoring or employment-related processes.",
        4: "Significant effect on employment opportunities, evaluation, discipline, compensation or working conditions.",
        5: "Severe or potentially irreversible employment harm or systemic adverse workforce impact.",
    },
    "Customer Impact": {
        1: "No meaningful individual customer impact.",
        2: "Minor inconvenience or easily reversible customer effect.",
        3: "Material but generally reversible effect on customer access, experience, treatment or decisions.",
        4: "Significant adverse customer consequence, denial, exclusion, loss or prolonged impact.",
        5: "Severe, widespread or potentially irreversible harm to customers or customer rights/interests.",
    },
    "Data Sensitivity": {
        1: "Public, synthetic or non-sensitive data only.",
        2: "Low-sensitivity internal data with limited adverse consequence if exposed or misused.",
        3: "Personal/internal data or moderately sensitive business data.",
        4: "Sensitive personal, confidential, regulated or high-value business data.",
        5: "Highly sensitive/restricted data, critical telecom data, large-scale sensitive personal data or data whose compromise could cause severe harm.",
    },
    "Personal Data Exposure": {
        1: "No personal data processed.",
        2: "Minimal personal data, strongly minimized or effectively de-identified.",
        3: "Personal data processed for a defined purpose with moderate scope.",
        4: "Large-scale, sensitive, linked, inferred or persistent personal data processing.",
        5: "Extensive or highly sensitive personal data exposure with severe privacy consequences or inability to reasonably remediate.",
    },
    "Privacy / Data Protection": {
        1: "No material privacy consequence.",
        2: "Minor privacy concern with low sensitivity and straightforward remediation.",
        3: "Material privacy impact requiring defined safeguards, transparency or assessment.",
        4: "Significant privacy risk involving sensitive data, profiling, monitoring, data sharing or rights impact.",
        5: "Severe privacy/data-protection impact, unlawful processing risk, irreversible disclosure, large-scale surveillance or serious rights impact.",
    },
    "Individual Consequence": {
        1: "No meaningful effect on an individual's interests, access, opportunities or wellbeing.",
        2: "Minor inconvenience or temporary, readily reversible effect.",
        3: "Material effect requiring intervention, correction or remediation.",
        4: "Significant effect on access, opportunity, finances, reputation, dignity or wellbeing.",
        5: "Severe or potentially irreversible harm to an individual, including serious deprivation, exclusion or loss.",
    },
    "Human Rights / Wellbeing": {
        1: "No credible rights or wellbeing impact.",
        2: "Low-level, temporary or indirect impact.",
        3: "Material impact on autonomy, dignity, accessibility, expression, equality, wellbeing or related interests.",
        4: "Significant rights/wellbeing impact requiring enhanced safeguards and oversight.",
        5: "Severe, systemic or potentially irreversible rights, dignity, safety or wellbeing harm.",
    },
    "Fairness & Non-Discrimination": {
        1: "No meaningful differential treatment or fairness concern.",
        2: "Minor disparity with low consequence and easy correction.",
        3: "Material disparity, bias or differential performance requiring mitigation.",
        4: "Significant unfair treatment or discriminatory outcome affecting important decisions or groups.",
        5: "Severe, systemic or unlawful discrimination, entrenched bias or large-scale exclusion.",
    },
    "Safety & Reliability": {
        1: "Failure produces negligible consequence; outputs are non-critical and easily checked.",
        2: "Occasional low-severity error with effective human correction.",
        3: "Material accuracy, robustness or reliability issue that can affect outcomes or operations.",
        4: "Significant unsafe, unreliable or unstable behavior with high-consequence effects.",
        5: "Severe or systemic safety/reliability failure capable of causing major harm or critical service impact.",
    },
    "Transparency & Explainability": {
        1: "No meaningful explanation need; use is obvious or low consequence.",
        2: "Basic disclosure/explanation is sufficient and available.",
        3: "Material decisions require understandable explanation; some limitations exist.",
        4: "Important outcomes are difficult to explain, challenge or trace, creating significant governance impact.",
        5: "Highly consequential decisions are opaque or effectively unchallengeable, creating severe accountability or rights impact.",
    },
    "Human Oversight & Autonomy": {
        1: "Human remains fully in control; AI cannot materially act or decide independently.",
        2: "Limited automation with easy human review and override.",
        3: "Meaningful automation; human review exists but may be periodic, selective or constrained.",
        4: "High autonomy or significant reliance on AI; human intervention may be delayed or difficult.",
        5: "AI can take highly consequential actions with little/no effective human oversight, override or intervention.",
    },
    "Cybersecurity": {
        1: "No material AI-specific security consequence.",
        2: "Limited attack surface with strong isolation and low-value exposure.",
        3: "Material AI-specific security risk such as prompt injection, model/data manipulation or misuse.",
        4: "Significant compromise could affect sensitive systems, data, integrations or business operations.",
        5: "Severe/systemic compromise, including privileged autonomous actions, critical infrastructure impact, major data compromise or uncontrolled propagation.",
    },
    "Legal & Regulatory": {
        1: "No material legal/regulatory consequence anticipated.",
        2: "Minor compliance issue with straightforward correction and no material external exposure.",
        3: "Material compliance obligation or breach risk requiring legal/regulatory review.",
        4: "Significant breach, regulatory intervention, contractual exposure or enforcement risk.",
        5: "Severe or prohibited legal/regulatory exposure, material sanction, licence/telecom impact or activity that cannot lawfully proceed.",
    },
    "Reputation & Trust": {
        1: "No meaningful external or internal trust impact.",
        2: "Minor localized concern with limited visibility.",
        3: "Material stakeholder concern or reputational impact requiring communication/remediation.",
        4: "Significant loss of customer, employee, regulator or partner trust; likely public scrutiny.",
        5: "Severe, sustained or enterprise-wide loss of trust, major public controversy or brand damage.",
    },
    "Societal Impact": {
        1: "No credible broader societal consequence.",
        2: "Limited indirect societal effect.",
        3: "Material effect on a community, market behavior, information environment or social outcomes.",
        4: "Significant broader impact affecting communities, public interests or social systems.",
        5: "Severe, systemic or large-scale societal harm, including manipulation, exclusion, destabilization or widespread adverse externalities.",
    },
}

LIKELIHOOD_DESCRIPTORS = {
    "Historical Occurrence": {
        1: "No known occurrence internally or in comparable contexts; scenario is exceptional.",
        2: "Rare or isolated occurrence in comparable environments.",
        3: "Scenario has occurred occasionally or credible examples exist in similar use cases.",
        4: "Similar events have occurred repeatedly internally or across comparable deployments.",
        5: "Issue is already occurring, recurring, or has a strong established history in the current environment.",
    },
    "Frequency of Use": {
        1: "Very infrequent or one-off use.",
        2: "Occasional use with limited transactions/interactions.",
        3: "Regular use as part of routine operations.",
        4: "Frequent use across daily/high-volume processes.",
        5: "Continuous, near-continuous or very high-volume use where exposure is persistent.",
    },
    "Scale of Exposure": {
        1: "Very limited exposure: few users, records, decisions or systems.",
        2: "Contained exposure to a small team, dataset or process.",
        3: "Moderate exposure across a function, customer segment or meaningful dataset.",
        4: "Broad exposure across multiple functions, large populations, integrations or datasets.",
        5: "Enterprise-wide, mass-market, ecosystem or critical-system exposure.",
    },
    "Duration / Persistence of Exposure": {
        1: "Short-lived, tightly time-bound exposure.",
        2: "Temporary exposure with limited persistence.",
        3: "Ongoing exposure during normal operation with periodic breaks or review.",
        4: "Persistent exposure over long periods with limited interruption.",
        5: "Continuous or enduring exposure where harmful conditions can accumulate or propagate.",
    },
    "Change / Volatility": {
        1: "Stable model, data, process and environment; changes are rare and tightly controlled.",
        2: "Low rate of change with established review and testing.",
        3: "Regular change in model, prompts, data, users or operating conditions.",
        4: "Frequent change, evolving dependencies or material drift/uncertainty.",
        5: "Highly dynamic or rapidly changing environment, model, agent behavior, data or external dependency with limited predictability.",
    },
    "Technical Feasibility": {
        1: "Scenario requires exceptional technical conditions and is difficult to reproduce.",
        2: "Technically difficult; requires uncommon conditions or sophisticated capability.",
        3: "Feasible with specific conditions, tooling or moderate technical capability.",
        4: "Readily feasible using common techniques, tools or known weaknesses.",
        5: "Trivial or inherent to normal operation; little technical barrier exists.",
    },
    "Access Required": {
        1: "Requires highly privileged, restricted or exceptional access.",
        2: "Requires elevated access available to a small number of trusted users.",
        3: "Requires authenticated or role-based access available to a defined user population.",
        4: "Can be triggered by ordinary users, broad internal access or externally exposed interfaces.",
        5: "No meaningful access barrier; public, automated or broadly accessible triggering is possible.",
    },
    "Skill / Complexity Required": {
        1: "Requires rare specialist expertise, significant preparation and complex execution.",
        2: "Requires advanced technical knowledge or meaningful effort.",
        3: "Requires moderate knowledge, experimentation or process understanding.",
        4: "Requires limited skill; common guidance/tools make the scenario easy to execute.",
        5: "Requires little/no specialist skill; can occur accidentally or through simple instructions/actions.",
    },
    "Foreseeable Misuse": {
        1: "Misuse is remote, implausible and inconsistent with realistic user behavior.",
        2: "Misuse is conceivable but requires unusual motivation or conditions.",
        3: "Misuse is reasonably foreseeable for certain users or contexts.",
        4: "Misuse is likely in common scenarios or attractive due to value/convenience.",
        5: "Misuse is obvious, easy, repeatedly observed or intrinsic to the way the system can be used.",
    },
    "Model / Data Susceptibility": {
        1: "Model/data are highly robust to the scenario; susceptibility is negligible.",
        2: "Limited susceptibility with strong technical constraints.",
        3: "Known sensitivity or weakness exists under certain inputs, data conditions or contexts.",
        4: "Model/data are materially susceptible to manipulation, drift, poisoning, leakage, bias or unstable behavior.",
        5: "High inherent susceptibility; harmful behavior is easy to induce, recurring or difficult to constrain.",
    },
}

CONTROL_DESCRIPTORS = {
    "Preventive Controls": {
        1: "Comprehensive preventive controls are implemented, enforced, tested and operating effectively; no material gaps identified.",
        2: "Multiple preventive controls operate effectively; only minor gaps or exceptions remain.",
        3: "Preventive controls exist and provide some protection, but important gaps, manual dependencies or untested assumptions remain.",
        4: "Preventive controls are incomplete, inconsistent, poorly enforced or readily bypassed.",
        5: "Preventive controls are absent, materially ineffective, not implemented or inappropriate for the risk.",
    },
    "Detective Controls": {
        1: "Comprehensive real-time/near-real-time detection is implemented, tested, tuned and linked to clear response actions.",
        2: "Effective monitoring and alerting cover the main risk indicators with minor gaps.",
        3: "Monitoring exists but has blind spots, manual review, limited thresholds or inconsistent response linkage.",
        4: "Detection is delayed, fragmented, poorly tuned or covers only a small part of the relevant risk.",
        5: "No meaningful monitoring, detection or alerting exists, or existing detection is known ineffective.",
    },
    "Human Oversight Controls": {
        1: "Human oversight is mandatory, competent, timely, independent where needed, and supported by clear override/stop mechanisms and evidence.",
        2: "Human oversight is effective and routinely performed with minor capacity or documentation gaps.",
        3: "Human review exists but is selective, periodic, dependent on individual judgment or inconsistently evidenced.",
        4: "Human oversight is weak, unclear, overloaded, too late to prevent harm or easy to bypass.",
        5: "No meaningful human review, accountability, intervention, override or stop capability exists.",
    },
    "Governance Controls": {
        1: "Ownership, approvals, roles, segregation, policy requirements, escalation and recordkeeping are clearly defined, consistently applied and evidenced.",
        2: "Governance is effective with minor process or documentation gaps.",
        3: "Core governance exists but some responsibilities, approval gates, escalation or evidence are incomplete or inconsistent.",
        4: "Governance is informal, fragmented, inconsistently applied, poorly documented or lacks effective escalation.",
        5: "No effective governance structure, accountable owner, approval route, policy requirement or escalation mechanism exists.",
    },
    "Control Validation / Testing": {
        1: "Control design and operating effectiveness are regularly tested, results are evidenced, deficiencies are remediated and independent challenge is used where appropriate.",
        2: "Testing demonstrates controls are generally effective; only minor findings or coverage gaps remain.",
        3: "Some testing/validation exists, but scope, frequency, evidence, independence or remediation is limited.",
        4: "Testing is ad hoc, stale, incomplete or reveals significant unresolved control weaknesses.",
        5: "No validation evidence exists, controls are untested, or testing demonstrates that controls are ineffective.",
    },
}


def all_descriptors() -> dict:
    return {
        "impact": IMPACT_DESCRIPTORS,
        "likelihood": LIKELIHOOD_DESCRIPTORS,
        "controls": CONTROL_DESCRIPTORS,
    }
