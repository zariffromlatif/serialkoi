# What Applink's docs answer (researched 20 Nov 2026)

Sources: Applink's provisioning guide and its form screenshots (dev.applink.com.bd/docs/provisioning),
the SMS/USSD/CaaS references and status codes on dev.applink.com.bd, and the docs of Ideamart
(docs.ideamart.io), which runs on the same hSenid platform.

| Question | Answer | Source |
|---|---|---|
| Server IP | You type it yourself in **"Allowed Host Address(es)"** on the first page of the create-app form. The field takes more than one address. Calls from any other address fail with E1303. Whether you can change it after approval is not documented. | Provisioning step 3; status codes |
| Test numbers | You list them yourself in **"Whitelisted Numbers"** on the same page. Until the app is approved for production ("limited production state"), only those numbers can use it (E1343). How many you may list is not documented. | Provisioning step 3; Ideamart provisioning guide |
| USSD code | Not one code per app. You pick a shared **Service Code** from a dropdown (the example shows 383) and set a **Keyword**, so the app's code looks like `*383*<keyword>#`. Whether extra digits after the keyword (`*383*<keyword>*4521#`) reach the app is **not documented**. | Provisioning step 10 |
| USSD charging | Per-menu charging is a switch ("Enable USSD Charging") you can turn off. "Subscription Required" is also a switch: turn it off for SerialKoi. | Provisioning steps 9–10 |
| CaaS | Configured in the form: min and max debit (the example shows ৳5 to ৳100). The form warns that "only mentioned charging amounts are available" and links to a list we could not see. The OTP is sent to the subscriber, and the docs mention SMS or USSD. | CaaS docs; provisioning step 16; Ideamart FAQ |
| SMS length | "Messages over the limit shall be broken up by the platform before sending." The limit is not stated. | SMS docs |
| SMS cost | In the SMS charging step, **Charged Party** is set to "Subscriber" at ৳2.00 per SMS in the example. The other options are not shown. If every alert costs the patient ৳2, a booking with 3 texts costs ৳6 on top of the ৳5 fee. | Provisioning step 8 |
| Bangla SMS | Not documented. The `encoding` field only lists Text (0), Flash (240) and Binary (245). | SMS docs; Ideamart SMS docs |
| Inbound SMS | Everyone texts a shared **short code** (the example shows 77000), starting with your **SMS Keyword**. The platform routes by keyword to your "Message Receiving URL". | Provisioning steps 6–7; Ideamart SMS guide |
| Phone numbers | An option, **"Enable Mobile Number Masking"**, replaces numbers with a hash. Leave it **off**: assistants type real numbers for walk-ins, and SMS to those must match. | Provisioning step 4; Ideamart provisioning guide |
| Throughput | Defaults shown: SMS 10 per second and 30,000 per day; USSD 10 per second and 10,000 per day. | Provisioning steps 7, 10 |
| Revenue share | Not published. The pricing page's 50% is a calculator default. | Pricing page |

## Settings to use when creating the app

- **Basic:** Allowed Host Address = the server's public IP. Whitelisted Numbers = your Banglalink test SIM(s).
- **Advanced:** Mobile Number Masking **off**. Advertisements **off**.
- **APIs:** SMS, USSD, CaaS. Subscription is not needed.
- **SMS:** Message Receiving URL `https://<host>/sms/receive`, Keyword `SK` (or whatever is free), delivery
  reports on (`/sms/report`). Charged party: pick a free option if one exists, otherwise ask support.
- **USSD:** Connection URL `https://<host>/ussd/receive`, Subscription Required **off**, USSD charging
  **off** (the ৳5 CaaS fee is the only charge).
- **CaaS:** Charging Notification URL `https://<host>/caas/chargingNotification`, minimum debit ৳5.
- Then set `SK_USSD_CODE` to the full code, e.g. `*383*44#`. SerialKoi reads the chamber code from the
  part after it (`*383*44*4521#`).
