import frappe, json
from frappe.model.document import Document
from erpnext.accounts.doctype.bank_guarantee.bank_guarantee import BankGuarantee
from frappe import _

class Nest_BankGuarantee(Document):
    def on_submit(self):
        frappe.msgprint ('Overridden')
        if not self.bank_guarantee_number:
            frappe.throw(_("Enter the Bank Guarantee Number before submittting."))
            frappe.msgprint("Overridden")

        if not self.bank:
            frappe.throw(_("Enter the name of the bank or lending institution before submittting."))
        return
