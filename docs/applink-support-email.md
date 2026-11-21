# Email to AppLink support (draft, not sent)

The docs answer the server IP, test numbers and inbound SMS questions (see applink-findings.md).
This version asks only what they don't.

**To:** support@applink.com.bd
**Subject:** AppQuest 2.0: USSD keyword, SMS charging and CaaS amounts

Hello AppLink team,

We are a BRAC University team in AppQuest 2.0 (Track A), building SerialKoi: patients book a doctor's
serial by USSD, pay a Tk5 booking fee through CaaS, and get SMS alerts when their turn is near. Before we
submit the application for approval, could you confirm:

1. **USSD:** If our app's code is *383*<keyword>#, can a subscriber dial *383*<keyword>*4521# and will
   the full string arrive in "message" at mo-init? (We use the extra digits as a chamber code.)
2. **SMS charging:** In the SMS charging settings, can the charged party be set so that alert SMS are free
   for the subscriber? We would rather charge once through CaaS than Tk2 for every alert.
3. **CaaS amounts:** Which one-time charge amounts are allowed? Is Tk5 one of them?
4. **Bangla SMS:** Which `encoding` value should /sms/send use for Bangla (UCS-2) text?
5. **Host address:** After approval, can we change the Allowed Host Address if we move servers?
6. **Callback source IPs:** Which IP addresses do AppLink's callbacks come from, so we can allow only those?
7. **Revenue share:** What share applies to CaaS charges for apps that go live after AppQuest?

Thank you,
Zarif Latif
Team [TEAM NAME], BRAC University
