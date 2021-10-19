# -*- coding: utf-8 -*-
# Copyright (c) 2021, QCS and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
#from _typeshed import Self, SupportsLessThanT
import frappe
from frappe.model.document import Document

class SalaryPayment(Document):
    # 1/4
    # This method runs on a New Salary Payment Entry ONLY to populate the Salary Slips into the Child table of the Salary Payment Document.
    
    # THE 'unpaid_salaries' TABLE IS COMPLETELY EDITABLE !! HENCE THE USER CAN MESS IT UP!!!

    # ********  Salary Payment - Save  ********
    def validate(self):
        if self.is_new():
            if self.department:
                ss = frappe.get_all("Salary Slip", filters={
                    "docstatus": "1",  
                    "start_date": (">=", self.posting_date), 
                    "payroll_entry": ["!=", ''], # *********************************  ADDED CONDITION  !!!********************************
                    #"salary_payment":("=", ""), 
                    "salary_payment":'',
                    "sponsoring_company": self.company, 
                    "department": self.department
                    }, fields=["name", "net_pay", "employee","employee_name","department", "payroll_entry"])
                
                if ss:
                    for item in ss:
                        self.append("unpaid_salaries",{
                            "employee": item.employee,
                            "employee_name": item.employee_name,
                            "salary_slip": item.name,
                            "net_pay": item.net_pay,
                            "department": item.department
                            })
            else:
                ss = frappe.get_all("Salary Slip", filters={
                    "docstatus": "1",  
                    "start_date": (">=", self.posting_date),
                    "payroll_entry": ["!=", ''], # *********************************  ADDED CONDITION  !!!********************************
                    #"salary_payment": ("=", ""), 
                    "salary_payment":'',
                    "sponsoring_company": self.company
                    }, fields=["name", "net_pay", "employee","employee_name", "payroll_entry"])
                frappe.errprint(ss)
                if ss:
                    for item in ss:
                        self.append("unpaid_salaries",{
                            "employee": item.employee,
                            "employee_name": item.employee_name,
                            "salary_slip": item.name,
                            "net_pay": item.net_pay,
                            "department": item.department
                            })

            total = 0            
            for item in self.get("unpaid_salaries"):
                total += item.net_pay
                #frappe.errprint(item.net_pay)
            self.total = total                

    # 2/4
    # This method Creates & Submits Payment (from Bank) against the Payroll Liabilities and Creates & Submits Inter-Company Adjustment Entries.
    # Finally, it submits all Leave Ledger Entries created during Salary Slip Creation.
    # ********  Salary Payment - On Submit  ********
    def on_submit(self):
        nest_jv = frappe.new_doc("Journal Entry")
        nest_jv.company = "National Engineering Services & Trading Co LLC"
        nest_jv.title = "Salary Payment: " + self.name + " Inter-Company Transaction"
        nest_jv.posting_date = self.real_posting_date
        nest_jv.naming_series = "JV/HR/.YY./.####"
        nest_jv.salary_payment = self.name

        nees_jv = frappe.new_doc("Journal Entry")
        nees_jv.company = "NEST Employment Services LLC"
        nees_jv.title = "Salary Payment: " + self.name + " Inter-Company Transaction"
        nees_jv.posting_date = self.real_posting_date
        nees_jv.naming_series = "NEE-JV/HR/.YY./.####"
        nees_jv.salary_payment = self.name

        fir_jv = frappe.new_doc("Journal Entry")
        fir_jv.company = "Firmo Technical Petroleum Services LLC"
        fir_jv.title = "Salary Payment: " + self.name + " Inter-Company Transaction"
        fir_jv.posting_date = self.real_posting_date
        fir_jv.naming_series = "FIRMO-JV/HR/.YY./.####"
        fir_jv.salary_payment = self.name  

        curr_total = 0

        for item in self.get("unpaid_salaries"):
            frappe.errprint("loop1")
            if not frappe.get_value("Salary Slip", item.salary_slip, "salary_payment"): # Salary Payment NOT linked to Salary Slip...
                frappe.errprint("salaryslip if")
                # if doc.company == salaryslip.sponsoring_company
                if frappe.get_value("Employee", item.employee, "company") == frappe.get_value("Employee", item.employee, "sponsoring_company"):
                    # ******************************** SAME COMPANY ******************************************
                    curr_total += item.net_pay
                    frappe.db.set_value("Salary Slip", item.salary_slip,"salary_payment", self.name)

                #if frappe.get_value("Employee", item.employee, "company") != frappe.get_value("Employee", item.employee, "sponsoring_company"): ************************
                else:
                    # ******************************** INTER COMPANY TRANSACTIONS ****************************
                    rec_ledger = ""
                    work_rec_ledger = ""
                    spon_comp = frappe.get_doc("Company", frappe.get_value("Employee", item.employee, "sponsoring_company"))
                    frappe.errprint('spon_company - ' + spon_comp.name)
                    working_comp = frappe.get_doc("Company", frappe.get_value("Employee", item.employee, "company"))
                    frappe.errprint('working_company - ' + working_comp.name)

                    for led in spon_comp.get("related_parties_receivable_account"):
                        #led.company = 
                        if led.company == frappe.get_value("Employee", item.employee, "company"):
                            rec_ledger = led.receivable_account
                            frappe.errprint('rec - ' + rec_ledger)

                    for led in working_comp.get("related_parties_receivable_account"):
                        if led.company == frappe.get_value("Employee", item.employee, "sponsoring_company"):
                            working_rec_ledger = led.receivable_account
                            frappe.errprint('working_rec - ' + working_rec_ledger)

                    frappe.errprint('Inter-Company Transaction Company: ' + working_comp.name)

                    if working_comp.name == "National Engineering Services & Trading Co LLC":        
                        frappe.errprint("working_comp")    
                        nest_jv.append("accounts",{
                                    "account": rec_ledger,
                                    "credit_in_account_currency": item.net_pay,
                                    "cost_center": frappe.get_value("Company", working_comp.company, "cost_center"),
                                    "party_type":"Employee",
                                    "party":item.employee,
                                    "user_remark":item.salary_slip  # *******************************************  ADDED LINE  ************************************
                                    })
                        nest_jv.append("accounts",{
                                    "account": frappe.get_value("Company", spon_comp.name, "default_payroll_payable_account") ,
                                    "cost_center": frappe.get_value("Company", working_comp.company, "cost_center"),
                                    "debit_in_account_currency": item.net_pay,
                                    "user_remark":item.salary_slip  # *******************************************  ADDED LINE  ************************************
                                    })
                        nest_jv.salary_payment = self.name
                        nest_jv.save()



                    if self.company == "National Engineering Services & Trading Co LLC":        
                            
                        nest_jv.append("accounts",{
                                    "account": rec_ledger,
                                    "cost_center": frappe.get_value("Company", self.company, "cost_center"),
                                    "debit_in_account_currency": item.net_pay,
                                    "party_type":"Employee",
                                    "party":item.employee,
                                    "user_remark":item.salary_slip  # *******************************************  ADDED LINE  ************************************
                                    })
                        nest_jv.append("accounts",{
                                    "account": self.bank_cash_account ,
                                    "cost_center": frappe.get_value("Company", self.company, "cost_center"),
                                    "credit_in_account_currency": item.net_pay,
                                    "user_remark":item.salary_slip  # *******************************************  ADDED LINE  ************************************
                                    })
                        nest_jv.salary_payment = self.name
                        nest_jv.save()
                        frappe.db.set_value("Salary Slip", item.salary_slip,"salary_payment", self.name)
                        

                    if working_comp.name == "NEST Employment Services LLC":        
                        frappe.errprint("working_comp")    
                        nees_jv.append("accounts",{
                                    "account": working_rec_ledger,
                                    "cost_center": frappe.get_value("Company", working_comp.company, "cost_center"),
                                    "credit_in_account_currency": item.net_pay,
                                    "party_type":"Employee",
                                    "party":item.employee,
                                    "user_remark":item.salary_slip  # *******************************************  ADDED LINE  ************************************
                                    })
                        nees_jv.append("accounts",{
                                    "account": frappe.get_value("Company", spon_comp.name, "default_payroll_payable_account") ,
                                    "cost_center": frappe.get_value("Company", self.company, "cost_center"),
                                    "debit_in_account_currency": item.net_pay,
                                    "user_remark":item.salary_slip  # *******************************************  ADDED LINE  ************************************
                                    })
                        nees_jv.salary_payment = self.name
                        nees_jv.save()



                    if self.company == "NEST Employment Services LLC":        
                            
                        nees_jv.append("accounts",{
                                    "account": rec_ledger,
                                    "cost_center": frappe.get_value("Company", self.company, "cost_center"),
                                    "debit_in_account_currency": item.net_pay,
                                    "party_type":"Employee",
                                    "party":item.employee,
                                    "user_remark":item.salary_slip  # *******************************************  ADDED LINE  ************************************
                                    })
                        nees_jv.append("accounts",{
                                    "account": self.bank_cash_account ,
                                    "cost_center": frappe.get_value("Company", self.company, "cost_center"),
                                    "credit_in_account_currency": item.net_pay,
                                    "user_remark":item.salary_slip  # *******************************************  ADDED LINE  ************************************
                                    })
                        nees_jv.salary_payment = self.name
                        nees_jv.save()
                        frappe.db.set_value("Salary Slip", item.salary_slip,"salary_payment", self.name)



                    if working_comp.name == "Firmo Technical Petroleum Services LLC":        
                        frappe.errprint("working_comp")    
                        fir_jv.append("accounts",{
                                    "account": working_rec_ledger,
                                    "cost_center": frappe.get_value("Company", working_comp.name, "cost_center"),
                                    "credit_in_account_currency": item.net_pay,
                                    "party_type":"Employee",
                                    "party":item.employee,
                                    "user_remark":item.salary_slip  # *******************************************  ADDED LINE  ************************************
                                    })
                        fir_jv.append("accounts",{
                                    "account": frappe.get_value("Company", working_comp.name, "default_payroll_payable_account"),
                                    "cost_center": frappe.get_value("Company", working_comp.name, "cost_center"),
                                    "debit_in_account_currency": item.net_pay,
                                    "user_remark":item.salary_slip  # *******************************************  ADDED LINE  ************************************
                                    })
                        fir_jv.salary_payment = self.name
                        fir_jv.save()


                    if self.company == "Firmo Technical Petroleum Services LLC":        
                            
                        fir_jv.append("accounts",{
                                    "account": rec_ledger,
                                    "cost_center": frappe.get_value("Company", self.company, "cost_center"),
                                    "debit_in_account_currency": item.net_pay,
                                    "party_type":"Employee",
                                    "party":item.employee,
                                    "user_remark":item.salary_slip  # *******************************************  ADDED LINE  ************************************
                                    })
                        fir_jv.append("accounts",{
                                    "account": self.bank_cash_account ,
                                    "cost_center": frappe.get_value("Company", self.company, "cost_center"),
                                    "credit_in_account_currency": item.net_pay,
                                    "user_remark":item.salary_slip  # *******************************************  ADDED LINE  ************************************
                                    })
                        fir_jv.salary_payment = self.name            
                        fir_jv.save()
                        frappe.db.set_value("Salary Slip", item.salary_slip,"salary_payment", self.name)

                # ***********************************   NOT REQUIRED. DONE IN 3/12 add_expense_claim()   ***************************************************************
                #for item in frappe.get_all('Expense Claim', filters={'status': 'Unpaid', 'employee': item.employee,
                #'docstatus':1, 'added_to_salary_slip':1}, fields=['name']):
                #    frappe.db.set_value("Salary Slip", item.name,"status", "Paid")
        
        if nest_jv.get("accounts"):
            nest_jv.submit()
        if nees_jv.get("accounts"):
            nees_jv.submit()
        if fir_jv.get("accounts"):
            fir_jv.submit()

            
        # ***************************************************** SAME COMPANY ENTRY ***********************************************
        if curr_total > 0:
            frappe.errprint('SAME COMPANY ENTRY ' + str(frappe.get_value("Company", self.company, "default_payroll_payable_account")))
            jv = frappe.new_doc("Journal Entry")
            jv.company = self.company
            jv.posting_date = self.real_posting_date
            jv.title = "Salary Payment: " + self.name + " Bank Payment"
            if self.company == "National Engineering Services & Trading Co LLC":
                jv.naming_series = "JV/HR/.YY./.####"
            if self.company == "NEST Employment Services LLC":
                jv.naming_series = "NEE-JV/HR/.YY./.####"
            if self.company == "Firmo Technical Petroleum Services LLC":
                jv.naming_series = "FIRMO-JV/HR/.YY./.####"
            #jv.naming_series = "JV/HR/.YY./.####" # ******************************* WRONG !!!!!!!!! ******************************
            jv.salary_payment = self.name 
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
            jv.submit()

        # ***************************************   Submit All Salary Slip Linked Leave Ledger Entries   ********************************
        frappe.errprint ('Submitting Leave Ledger Entries')
        for item in self.get("unpaid_salaries"):
            
            for lle in frappe.get_all("Leave Ledger Entry", filters={"transaction_name": item.salary_slip, "docstatus": 0}, fields=["name"]):
                frappe.errprint("LLE Found")
                lle_doc = frappe.get_doc("Leave Ledger Entry", lle.name)
                lle_doc.save()
                lle_doc.submit()

    # 3/4
    # This method unmarks all selected 'Salary Slip' documents, and Cancels and Deletes all Journal Entries created with this Salary Payment.
    # ********  Salary Payment - On Cancel  ********
    def on_cancel(self):
        self.my_clear()

    # 4/4
    # This method unmarks all selected 'Salary Slip' documents, and Cancels and Deletes all Journal Entries created with this Salary Payment.
    #def on_trash(self):
    #    #self.my_clear()
    #    frappe.errprint("before_trash")


    def my_clear(self):
        for item in self.get("unpaid_salaries"):
            frappe.errprint('Clearing Salary Slip link to this Salary Payment for ' + item.employee_name)
            frappe.db.set_value("Salary Slip", item.salary_slip,"salary_payment", "")
        frappe.errprint('Done - Clearing Salary Slip link to this Salary Payment.')
        for item in frappe.get_all('Journal Entry', filters={'docstatus': 1, 'salary_payment': self.name}, fields=['name']):
            frappe.errprint('Cancelling and Deleting all Salary Payment related JVs ' + item.name)
            jv = frappe.get_doc("Journal Entry", item.name)
            jv.cancel() # ******************************************* Re-Enabled ***************************************
            jv.delete() # ******************************************* Added Line ***************************************
        frappe.errprint('Done - Cancelling and Deleting all Salary Payment related JVs')

        # Create reversal entries in Leave Ledger Entry against all submitted entries related to this Salary Payment and Submit the same
        # Then, Create new set of Ledger Entries in Draft Mode.
        # frappe.msgprint('Cancelling Salary Payment does not cancel Leave Ledger Entries Created during Payroll Entry Process. Please Create Negative days entries in the leave ledger accordingly.')
        for item in self.get("unpaid_salaries"):
            frappe.errprint('Reversing LLE and regenerating for ' + item.employee_name)
            ss=item.salary_slip
            frappe.errprint(ss)
            for lle in frappe.get_all('Leave Ledger Entry', filters={
                'docstatus': 1, # Submitted
                'salary_slip' : ss #ss.name
                }, fields=['name', 'employee', 'leave_type', 'salary_slip', 'from_date', 'to_date', 'leaves']):

                frappe.errprint('Found LLEs.')
                
                # 1- Negative Entries SUBMITTED
                ll = frappe.new_doc("Leave Ledger Entry")
                ll.employee = lle.employee
                ll.leave_type = lle.leave_type
                ll.salary_slip = lle.salary_slip
                ll.from_date = lle.from_date
                ll.to_date = lle.to_date
                ll.leaves = -lle.leaves
                ll.save()
                ll.submit()

                # 2- Positive Entries DRAFT
                ll = frappe.new_doc("Leave Ledger Entry")
                ll.employee = lle.employee
                ll.leave_type = lle.leave_type
                ll.salary_slip = lle.salary_slip
                ll.from_date = lle.from_date
                ll.to_date = lle.to_date
                ll.leaves = lle.leaves
                ll.save()

        frappe.errprint('Done - Reversal and regeneration of LLEs.')    
