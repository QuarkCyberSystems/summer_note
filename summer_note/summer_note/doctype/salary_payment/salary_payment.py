# -*- coding: utf-8 -*-
# Copyright (c) 2021, QCS and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document

class SalaryPayment(Document):
    def validate(self):
        if self.is_new():
            if self.department:    
                for item in frappe.get_all("Salary Slip", filters={"docstatus": "1",  "start_date":(">=", self.posting_date), "salary_payment":("=", ""), "sponsoring_company":self.company, "department":self.department}, fields=["name", "net_pay", "employee","employee_name","department"]):
                    self.append("unpaid_salaries",{
                        "employee":item.employee,
                        "employee_name":item.employee_name,
                        "salary_slip":item.name,
                        "net_pay":item.net_pay,
                        "department": item.department
                        })
            else:
                for item in frappe.get_all("Salary Slip", filters={"docstatus": "1",  "start_date":(">=", self.posting_date), "salary_payment":("=", ""), "sponsoring_company":self.company}, fields=["name", "net_pay", "employee","employee_name"]):
                    self.append("unpaid_salaries",{
                        "employee":item.employee,
                        "employee_name":item.employee_name,
                        "salary_slip":item.name,
                        "net_pay":item.net_pay
                        })

            total = 0            
            for item in self.get("unpaid_salaries"):
                total += item.net_pay
                frappe.errprint(item.net_pay)
            self.total = total                



                    
             

    def on_submit(self):
        nest_jv = frappe.new_doc("Journal Entry")
        nest_jv.company = "National Engineering Services & Trading Co LLC"
        nest_jv.posting_date = self.real_posting_date
        nest_jv.naming_series = "JV/HR/.YY./.####"
        nest_jv.salary_payment = self.name
        nees_jv = frappe.new_doc("Journal Entry")
        nees_jv.company = "NEST Employment Services LLC"
        nees_jv.posting_date = self.real_posting_date
        nees_jv.naming_series = "NEE-JV/HR/.YY./.####"
        nees_jv.salary_payment = self.name
        fir_jv = frappe.new_doc("Journal Entry")
        fir_jv.company = "Firmo Technical Petroleum Services LLC"
        fir_jv.posting_date = self.real_posting_date
        fir_jv.naming_series = "FIRMO-JV/HR/.YY./.####"
        fir_jv.salary_payment = self.name  
        curr_total = 0        
        for item in self.get("unpaid_salaries"):
            frappe.errprint("loop1")
            if not frappe.get_value("Salary Slip", item.salary_slip, "salary_payment"):
                frappe.errprint("salaryslip if")
                # if doc.company == salaryslip.sponsoring_company
                if frappe.get_value("Employee", item.employee, "company") == frappe.get_value("Employee", item.employee, "sponsoring_company"):
                    #total  
                    curr_total += item.net_pay
                    frappe.db.set_value("Salary Slip", item.salary_slip,"salary_payment", self.name)

                if frappe.get_value("Employee", item.employee, "company") != frappe.get_value("Employee", item.employee, "sponsoring_company"):
                    rec_ledger = ""
                    work_rec_ledger = ""
                    spon_comp = frappe.get_doc("Company", frappe.get_value("Employee", item.employee, "sponsoring_company"))
                    working_comp = frappe.get_doc("Company", frappe.get_value("Employee", item.employee, "company"))
                    for led in spon_comp.get("related_parties_receivable_account"):
                        if led.company == frappe.get_value("Employee", item.employee, "company"):
                            rec_ledger = led.receivable_account
                    for led in working_comp.get("related_parties_receivable_account"):
                        if led.company == frappe.get_value("Employee", item.employee, "sponsoring_company"):
                            working_rec_ledger = led.receivable_account

                    frappe.errprint(working_comp.name)

                    if working_comp.name == "National Engineering Services & Trading Co LLC":        
                        frappe.errprint("working_comp")    
                        nest_jv.append("accounts",{
                                    "account": working_rec_ledger,
                                    "credit_in_account_currency": item.net_pay,
                                    "party_type":"Employee",
                                    "party":item.employee,
                                    })
                        nest_jv.append("accounts",{
                                    "account": frappe.get_value("Company", spon_comp.name, "default_payroll_payable_account") ,
                                    "debit_in_account_currency": item.net_pay,
                                    })
                        nest_jv.salary_payment = self.name
                        nest_jv.save()



                    if self.company == "National Engineering Services & Trading Co LLC":        
                            
                        nest_jv.append("accounts",{
                                    "account": rec_ledger,
                                    "debit_in_account_currency": item.net_pay,
                                    "party_type":"Employee",
                                    "party":item.employee,
                                    })
                        nest_jv.append("accounts",{
                                    "account": self.bank_cash_account ,
                                    "credit_in_account_currency": item.net_pay,
                                    })
                        nest_jv.salary_payment = self.name
                        nest_jv.save()
                        frappe.db.set_value("Salary Slip", item.salary_slip,"salary_payment", self.name)
                        

                    if working_comp.name == "NEST Employment Services LLC":        
                        frappe.errprint("working_comp")    
                        nees_jv.append("accounts",{
                                    "account": working_rec_ledger,
                                    "credit_in_account_currency": item.net_pay,
                                    "party_type":"Employee",
                                    "party":item.employee,
                                    })
                        nees_jv.append("accounts",{
                                    "account": frappe.get_value("Company", spon_comp.name, "default_payroll_payable_account") ,
                                    "debit_in_account_currency": item.net_pay,
                                    })
                        nees_jv.salary_payment = self.name
                        nees_jv.save()



                    if self.company == "NEST Employment Services LLC":        
                            
                        nees_jv.append("accounts",{
                                    "account": rec_ledger,
                                    "debit_in_account_currency": item.net_pay,
                                    "party_type":"Employee",
                                    "party":item.employee,
                                    })
                        nees_jv.append("accounts",{
                                    "account": self.bank_cash_account ,
                                    "credit_in_account_currency": item.net_pay,
                                    })
                        nees_jv.salary_payment = self.name
                        nees_jv.save()
                        frappe.db.set_value("Salary Slip", item.salary_slip,"salary_payment", self.name)



                    if working_comp.name == "Firmo Technical Petroleum Services LLC":        
                        frappe.errprint("working_comp")    
                        fir_jv.append("accounts",{
                                    "account": working_rec_ledger,
                                    "credit_in_account_currency": item.net_pay,
                                    "party_type":"Employee",
                                    "party":item.employee,
                                    })
                        fir_jv.append("accounts",{
                                    "account": frappe.get_value("Company", spon_comp.name, "default_payroll_payable_account") ,
                                    "debit_in_account_currency": item.net_pay,
                                    })
                        fir_jv.salary_payment = self.name
                        fir_jv.save()


                    if self.company == "Firmo Technical Petroleum Services LLC":        
                            
                        fir_jv.append("accounts",{
                                    "account": rec_ledger,
                                    "debit_in_account_currency": item.net_pay,
                                    "party_type":"Employee",
                                    "party":item.employee,
                                    })
                        fir_jv.append("accounts",{
                                    "account": self.bank_cash_account ,
                                    "credit_in_account_currency": item.net_pay,
                                    })
                        fir_jv.salary_payment = self.name            
                        fir_jv.save()
                        frappe.db.set_value("Salary Slip", item.salary_slip,"salary_payment", self.name)

                for item in frappe.get_all('Expense Claim', filters={'status': 'Unpaid', 'employee': item.employee,
                'docstatus':1, 'added_to_salary_slip':1}, fields=['name']):
                    frappe.db.set_value("Salary Slip", item.name,"status", "Paid")


            
        if curr_total > 0:
            jv = frappe.new_doc("Journal Entry")
            jv.company = self.company
            jv.posting_date = self.real_posting_date
            jv.naming_series = "JV/HR/.YY./.####"
            jv.salary_payment = self.name 
            frappe.errprint(frappe.get_value("Company", jv.company, "default_payroll_payable_account"))
            jv.append("accounts",{
                        "account": frappe.get_value("Company", jv.company, "default_payroll_payable_account"),
                        "debit_in_account_currency": curr_total,
                        })
            jv.append("accounts",{
                        "account": self.bank_cash_account,
                        "credit_in_account_currency": curr_total,
                        })
            jv.salary_payment = self.name            
            jv.save()
        

    def on_cancel(self):
        for item in self.get("unpaid_salaries"):
            frappe.db.set_value("Salary Slip", item.salary_slip,"salary_payment", "")
        for item in frappe.get_all('Journal Entry', filters={'docstatus': 1, 'salary_payment': self.name}, fields=['name']):
            jv = frappe.get_doc("Journal Entry", item.name)
            #jv.cancel()            





        
                

            