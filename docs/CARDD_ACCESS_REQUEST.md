# CarDD dataset access — request draft (human submit only)

**Do not automate this.** PIC Lab requires a signed licensing form and email.
AI Tribe must **not** download CarDD until access is granted and
`/mnt/ml-scratch/damage_datasets/LICENSE_ACK.json` is updated with a
CarDD-specific acknowledgement.

Form PDF: [CarDD_license.pdf](https://cardd-ustc.github.io/docs/CarDD_license.pdf)

Send completed form to: **wangxk0624@mail.ustc.edu.cn**

---

## Licensing form fields (fill by hand / PDF)

| Field | Suggested content |
| --- | --- |
| **Affiliation** | Independent researcher / personal AI lab (Motor Damage Assessment POC) |
| **Name** | Bipul Sahay |
| **Email** | *(your email)* |
| **Signature** | *(sign the PDF)* |

By signing, you agree to PIC Lab terms: research/scientific use only; no
commercial use or redistribution without prior PIC Lab authorization; cite the
CarDD TITS paper in any publication.

---

## Email draft (copy, edit, send yourself)

**To:** wangxk0624@mail.ustc.edu.cn  
**Subject:** CarDD dataset access request — non-commercial research (AI Tribe motor damage lab)

Dear Dr. Wang,

I am writing to request access to the CarDD dataset under the terms described in
[CarDD_license.pdf](https://cardd-ustc.github.io/docs/CarDD_license.pdf).

**Affiliation:** Independent researcher (personal AI / insurance lab prototype)  
**Name:** Bipul Sahay  
**Email:** *(your email)*

**Intended use:** Non-commercial research and educational evaluation only. I am
building a proof-of-concept motor damage assessment pipeline for lab
demonstrations. CarDD would be used **offline** on a private research VM to:

- Benchmark damage detection/segmentation models against published CarDD baselines
- Compare with an existing Hugging Face damage classifier already used in the POC
- Explore future segmentation upgrades (not for live commercial deployment)

**Environment:** Dataset would be stored on a dedicated research scratch volume
(`/mnt/ml-scratch/cardd/`) on a private Oracle Cloud VM. It would **not** be
committed to git, redistributed, or used to train models deployed in any
commercial insurance product without separate written authorization from PIC Lab.

**Commercial status:** This is personal / lab research only, not an insurer
production system. I understand commercial use requires prior PIC Lab authorization.

I have attached the completed licensing form (signed). Please let me know if
any additional information is required.

Thank you for making CarDD available to the research community.

Best regards,  
Bipul Sahay  
*(optional: link to public repo https://github.com/bipulsin/AI_Tribe if you wish)*

---

## After approval

1. Download CarDD to `/mnt/ml-scratch/cardd/raw/` only.
2. Update `LICENSE_ACK.json`:

```json
{
  "cardd_access": {
    "approved": true,
    "approved_at": "YYYY-MM-DD",
    "approved_by": "PIC Lab",
    "note": "Non-commercial lab research only; not for live tribe.tradentical.com retrain without re-check."
  }
}
```

3. Do **not** merge CarDD-derived labels into live VMMR training paths until
license terms are re-confirmed at that time (same rule as VehiDE lab labels).
