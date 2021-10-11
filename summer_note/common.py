from __future__ import unicode_literals
import frappe, requests, urllib3, json, datetime, dateutil.parser, urllib, dateutil.relativedelta
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import flt, add_days, date_diff, get_request_site_address, formatdate, getdate, month_diff, today
from erpnext.hr.doctype.employee.employee import get_holiday_list_for_employee
from erpnext.accounts.utils import get_balance_on
from json import dumps
from datetime import date, timedelta, datetime
from frappe.utils.response import json_handler
from dateutil.relativedelta import relativedelta


# 1/9
# This adds a Project agaist Every SO except for Engineering Sertvices and Vendor Projects.
def add_project(sales_order, method):
    if sales_order.project_type != "Engineering Services" or sales_order.project_type != "Vendor Projects":
        proj = frappe.new_doc("Project")
        proj.project_name = sales_order.name
        proj.customer = sales_order.customer
        proj.sales_order = sales_order.name 
        proj.project_type = sales_order.project_type
        proj.expected_end_date = sales_order.delivery_date
        proj.save(ignore_permissions=True)
        sales_order.project = proj.name
    
# 2/9
# This method adds "Additional Salary" Document as "OT1" and "OT2" SalarySlip components
# which is pulled during Payroll Processing, for the OT1 and OT2 Hours Submitted.
# The OT1 & OT2 are calculated based on Basic Salary Only.
def ot_timesheet(timesheet, method):
    emp = frappe.get_doc("Employee", timesheet.employee)
    ot1 = 0
    ot2 = 0
    basic = 0
    
    ssta = frappe.get_value("Salary Structure Assignment", {"employee":emp.name, "docstatus":"1"}, "salary_structure")
    sst = frappe.get_doc("Salary Structure", ssta)
    for item in sst.get("earnings"):
        if item.salary_component == "Basic":
            basic = item.amount
        if item.salary_component == "Op.Basic":
            basic = item.amount    

    if emp.ot_entitled:
        for item in timesheet.get("time_logs"):
            if item.ot == "OT1":
                ot1 += (basic * 12/365/8 * item.hours * 1.25)
            if item.ot == "OT2": 
                ot2 += (basic * 12/365/8 * item.hours * 1.5)

    if ot1 > 0:
        sas = frappe.new_doc("Additional Salary")
        sas.payroll_date = timesheet.date
        sas.employee = timesheet.employee
        sas.salary_component = "OT1"
        sas.amount = ot1
        sas.company = timesheet.company
        sas.series = "HR-ADS-.YY.-.MM.-"
        sas.save()
        sas.submit()

    if ot2 > 0:
        sas = frappe.new_doc("Additional Salary")
        sas.payroll_date = timesheet.date
        sas.employee = timesheet.employee
        sas.salary_component = "OT2"
        sas.amount = ot2
        sas.company = timesheet.company
        sas.series = "HR-ADS-.YY.-.MM.-"
        sas.save()
        sas.submit()

#3/9
# This code adds an EXPENSE CLAIM Entry under PAYROLL CONTROL Account, to be reversed during Posting/Submission of Payroll Slips.
# The standard functionality of ERPNext will add an Additional Salary Entry once an Expense Claim has been Submitted.
def add_expense_claim(salary_slip, method):
    #emp = salary_slip.employee
    if salary_slip.expense_claim_added == 0:
        exp_claim =  frappe.get_all('Expense Claim', filters={
                'status': 'Unpaid',
                'employee': salary_slip.employee,
                'docstatus':1
            }, fields=['name', 'total_sanctioned_amount'])
        claim_total = 0
        #*******************************************************************************************************************************
        # ADDED CODE
        claims=""
        #*******************************************************************************************************************************

        account_ledger = ""
        ssta = frappe.get_value("Salary Structure Assignment", {"employee":salary_slip.employee, "docstatus":"1"}, "salary_structure")
        sst = frappe.get_doc("Salary Structure", ssta)
        for item in sst.get("earnings"):
            if item.salary_component == "Expense Claim":
                sc = frappe.get_doc("Salary Component", item.salary_component)
                for comp in sc.get("accounts"):
                    if comp.company == salary_slip.company:
                        account_ledger = comp.default_account
            
            if item.salary_component == "Op.Expense Claim":
                sc = frappe.get_doc("Salary Component", item.salary_component)
                for comp in sc.get("accounts"):
                    if comp.company == salary_slip.company:
                        account_ledger = comp.default_account


        
        for item in exp_claim:
            claim_total += item.total_sanctioned_amount
            #*******************************************************************************************************************************
            # ADDED CODE
            claims += item.name + ", "
            #*******************************************************************************************************************************
           #frappe.set_value('Expense Claim', item.name, 'status', 'Paid')
            frappe.set_value('Expense Claim', item.name, 'added_to_salary_slip', 1)
            frappe.set_value('Expense Claim', item.name, 'salary_slip', salary_slip.name)
        
        #*******************************************************************************************************************************
        # ADDED CODE - Needs Improvement to remove last comma (,)
        claims.strip()
        claims = claims[:-1]
        #*******************************************************************************************************************************
        salary_slip.append("earnings",{
                    "salary_component":"Expense Claim",
                    "amount":claim_total
                    })
        salary_slip.expense_claim_added = 1

        #*******************************************************************************************************************************
        # ADDED CODE
        nest_cc = frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center")
        #nest_cc = frappe.get_value("Company", salary_slip.company, "cost_center")
        #*******************************************************************************************************************************
        salary_exp_account = frappe.get_value("Company", salary_slip.company, "default_payroll_payable_account")
        exp_account = frappe.get_value("Company", salary_slip.company, "default_expense_claim_payable_account")
        pay_control = frappe.get_value("Company", salary_slip.company, "payroll_controll")
        jv = frappe.new_doc("Journal Entry")
        jv.company = salary_slip.company
        jv.posting_date = salary_slip.posting_date
        #if salary_slip.company == ""
        if salary_slip.company == "National Engineering Services & Trading Co LLC":
            jv.naming_series = "JV/HR/.YY./.####"
        if salary_slip.company == "NEST Employment Services LLC":
            jv.naming_series = "NEE-JV/HR/.YY./.####"
        if salary_slip.company == "Firmo Technical Petroleum Services LLC":
            jv.naming_series = "FIRMO-JV/HR/.YY./.####"        
        jv.voucher_type = "Journal Entry"
        if claim_total > 0:
            jv.append("accounts",{
                    "account": exp_account,
                    "party_type":"Employee",
                    "party":salary_slip.employee,
                    "debit_in_account_currency": claim_total,
                    #*******************************************************************************************************************************
                    # ADDED CODE
                    #*******************************************************************************************************************************
                    "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                    "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                    "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                    "employee":salary_slip.employee,
                    "user_remark": claims

                    })
            jv.append("accounts",{
                    "account": pay_control,
                    "credit_in_account_currency": claim_total,
                    #*******************************************************************************************************************************
                    # ADDED CODE
                    #*******************************************************************************************************************************
                    "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                    "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                    "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                    "employee":salary_slip.employee,
                    "user_remark": claims
                  })

            jv.salary_slip = salary_slip.name
            jv.save()
            
        salary_slip.calculate_net_pay()     

#4/9
# This creates the INTERCOMPANY Transactions when submitting "Salary Payment" Document.
@frappe.whitelist()
def inter_company(start_date, end_date, payroll_entry):
    
    nees_nest_rec_ledger = ""
    nees_fir_rec_ledger = ""
    nest_nees_rec_ledger = ""
    nest_fir_rec_ledger = ""
    fir_nest_rec_ledger = ""
    fir_nees_rec_ledger = ""
    jcomp = frappe.get_doc("Company", "National Engineering Services & Trading Co LLC")
    for item in jcomp.get("related_parties_receivable_account"):
        if item.company == "NEST Employment Services LLC":
            nest_nees_rec_ledger = item.receivable_account
        if item.company == "Firmo Technical Petroleum Services LLC":
            nest_fir_rec_ledger = item.receivable_account

    jcomp = frappe.get_doc("Company", "NEST Employment Services LLC")
    for item in jcomp.get("related_parties_receivable_account"):
        if item.company == "National Engineering Services & Trading Co LLC":
            nees_nest_rec_ledger = item.receivable_account
        if item.company == "Firmo Technical Petroleum Services LLC":
            nees_fir_rec_ledger = item.receivable_account

    jcomp = frappe.get_doc("Company", "Firmo Technical Petroleum Services LLC")
    for item in jcomp.get("related_parties_receivable_account"):
        if item.company == "National Engineering Services & Trading Co LLC":
            fir_nest_rec_ledger = item.receivable_account
        if item.company == "NEST Employment Services LLC":
            fir_nees_rec_ledger = item.receivable_account                    

    nest_sp = 0
    nest_nee_rec = 0
    nest_fir_rec = 0
    nees = 0
    nees_nest_rec = 0
    nees_fir_rec = 0
    fir = 0
    fir_nest_rec = 0
    fir_nees_rec = 0

    for item in frappe.get_all("Salary Slip", filters={"docstatus": "1",  "start_date":("=", start_date), "end_date":("=", end_date), "payroll_entry":payroll_entry}, fields=["name", "net_pay", "employee"]):
        #frappe.errprint(item.employee)
        if frappe.get_value("Employee", item.employee, "sponsoring_company") == "National Engineering Services & Trading Co LLC":
            nest_sp += item.net_pay
            if frappe.get_value("Employee", item.employee, "company") == "NEST Employment Services LLC":
                nest_nee_rec += item.net_pay
            if frappe.get_value("Employee", item.employee, "company") == "Firmo Technical Petroleum Services LLC":
                nest_fir_rec += item.net_pay    
        if frappe.get_value("Employee", item.employee, "sponsoring_company") == "NEST Employment Services LLC":
            nees += item.net_pay
            #frappe.errprint(item.net_pay)
            if frappe.get_value("Employee", item.employee, "company") == "National Engineering Services & Trading Co LLC":
                nees_nest_rec += item.net_pay
            if frappe.get_value("Employee", item.employee, "company") == "Firmo Technical Petroleum Services LLC":
                nees_fir_rec += item.net_pay
        if frappe.get_value("Employee", item.employee, "sponsoring_company") == "Firmo Technical Petroleum Services LLC":
            fir += item.net_pay
            if frappe.get_value("Employee", item.employee, "company") == "National Engineering Services & Trading Co LLC":
                fir_nest_rec += item.net_pay
            if frappe.get_value("Employee", item.employee, "company") == "NEST Employment Services LLC":
                fir_nees_rec += item.net_pay



                   
    nest_jv = frappe.new_doc("Journal Entry")
    nest_jv.company = "National Engineering Services & Trading Co LLC"
    nest_jv.posting_date = end_date
    nest_jv.naming_series = "JV/HR/.YY./.####"

    nees_jv = frappe.new_doc("Journal Entry")
    nees_jv.company = "NEST Employment Services LLC"
    nees_jv.posting_date = end_date
    nees_jv.naming_series = "JV/HR/.YY./.####"


    fir = frappe.new_doc("Journal Entry")
    fir_jv.company = "NEST Employment Services LLC"
    fir_jv.posting_date = end_date
    fir_jv.naming_series = "JV/HR/.YY./.####"


    for item in frappe.get_all("Salary Slip", filters={"docstatus": "1",  "start_date":("=", start_date), "end_date":("=", end_date), "payroll_entry":payroll_entry}, fields=["name", "net_pay", "employee"]):
        if frappe.get_value("Employee", item.employee, "sponsoring_company") == frappe.get_value("Employee", item.employee, "company"):
            curr_comp_total += item.net_pay
        if frappe.get_value("Employee", item.employee, "sponsoring_company") == "National Engineering Services & Trading Co LLC" and frappe.get_value("Employee", item.employee, "sponsoring_company") != frappe.get_value("Employee", item.employee, "company") :
            rec_ledger = ""
            cur_comp = frappe.get_doc("Company", salary_slip.company)
            for led in cur_comp.get("related_parties_receivable_account"):
                if led.company == item.company:
                    rec_ledger = item.receivable_account 
                nest_jv.append("accounts",{
                            "account": rec_ledger,
                            "debit_in_account_currency": item.net_pay,
                            "party_type":"Employee",
                            "party":item.employee,
                            #*******************************************************************************************************************************
                            # ADDED CODE
                            #*******************************************************************************************************************************
                            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                            "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                            "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                            "employee":salary_slip.employee,
                            "user_remark":item.name
                            })
                nest_jv.append("accounts",{
                            "account": frappe.get_value("Company", "National Engineering Services & Trading Co LLC", "payroll_bank"),
                            "credit_in_account_currency": item.net_pay,
                            "cost_center":frappe.get_value("Department", frappe.get_value("Employee", item.employee, "department"), "cost_center"),
                            #*******************************************************************************************************************************
                            # ADDED CODE
                            #*******************************************************************************************************************************
                            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                            "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                            "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                            "employee":salary_slip.employee,
                            "user_remark":item.name
                            })
                nest_jv.save()            

        if frappe.get_value("Employee", item.employee, "sponsoring_company") == "NEST Employment Services LLC" and frappe.get_value("Employee", item.employee, "sponsoring_company") != frappe.get_value("Employee", item.employee, "company") :
            rec_ledger = ""
            cur_comp = frappe.get_doc("Company", salary_slip.company)
            for led in cur_comp.get("related_parties_receivable_account"):
                if led.company == item.company:
                    rec_ledger = item.receivable_account 
                nees_jv.append("accounts",{
                            "account": rec_ledger,
                            "debit_in_account_currency": item.net_pay,
                            "party_type":"Employee",
                            "party":item.employee,
                            #*******************************************************************************************************************************
                            # ADDED CODE
                            #*******************************************************************************************************************************
                            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                            "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                            "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                            "employee":salary_slip.employee,
                            "user_remark":item.name
                            
                            })
                nees_jv.append("accounts",{
                            "account": frappe.get_value("Company", "NEST Employment Services LLC", "payroll_bank"),
                            "credit_in_account_currency": item.net_pay,
                            #*******************************************************************************************************************************
                            # ADDED CODE
                            #*******************************************************************************************************************************
                            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                            "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                            "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                            "employee":salary_slip.employee,
                            "user_remark":item.name
                            })
                nees_jv.save()            


        if frappe.get_value("Employee", item.employee, "sponsoring_company") == "Firmo Technical Petroleum Services LLC" and frappe.get_value("Employee", item.employee, "sponsoring_company") != frappe.get_value("Employee", item.employee, "company") :
            rec_ledger = ""
            cur_comp = frappe.get_doc("Company", salary_slip.company)
            for led in cur_comp.get("related_parties_receivable_account"):
                if led.company == item.company:
                    rec_ledger = item.receivable_account 
                fir_jv.append("accounts",{
                            "account": rec_ledger,
                            "debit_in_account_currency": item.net_pay,
                            "party_type":"Employee",
                            "party":item.employee,
                            #*******************************************************************************************************************************
                            # ADDED CODE
                            #*******************************************************************************************************************************
                            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                            "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                            "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                            "employee":salary_slip.employee,
                            "user_remark":item.name

                            })
                fir_jv.append("accounts",{
                            "account": frappe.get_value("Company", "Firmo Technical Petroleum Services LLC", "payroll_bank"),
                            "credit_in_account_currency": item.net_pay,
                            #*******************************************************************************************************************************
                            # ADDED CODE
                            #*******************************************************************************************************************************
                            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                            "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                            "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                            "employee":salary_slip.employee,
                            "user_remark":item.name
                            })
                fir_jv.save()                                                    

    if curr_comp_total > 0:
        jv = frappe.new_doc("Journal Entry")
        jv.company = frappe.get_value("Payroll Entry", payroll_entry, "company")
        
        jv.posting_date = end_date
        jv.naming_series = "JV/HR/.YY./.####"
        jv.append("accounts",{
                        "account": frappe.get_value("Company", jv.company, "default_payroll_payable_account"),
                        "debit_in_account_currency": curr_comp_total
                        })
        jv.append("accounts",{
                        "account": frappe.get_value("Payroll Entry", payroll_entry, "payment_account"),
                        "credit_in_account_currency": curr_comp_total,
                        #*******************************************************************************************************************************
                        # ADDED CODE
                        #*******************************************************************************************************************************
                        "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                        "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                        "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                        "employee":salary_slip.employee,
                        "user_remark":payroll_entry.name
                        })
        jv.save()                

    

    frappe.msgprint("Inter Company WPS JVs have been set to draft")

#5/9    
# This method adds a "Additional Salary" document as "Additional Dues" Salary Component into the "SalarySlip" against "LEAVE APPLICATIONs" Taken by the employee.
# It depends on the Annual Leave days taken and selection of flag in the Leave application to include_all_leave_salary_and_airfare_dues_with_next_payment.                        
def add_dues(leave_application, method):
#*******************************************************************************************************************************
# ONLY APPROVED (STATUS) AND SUBMITTED (DOCUMENT STATUS) ENTRIES ARE TO BE CONSIDERED. CONFIRM SELECTION!
#*******************************************************************************************************************************
    if leave_application.status == "Approved":
        company = frappe.get_value("Employee", leave_application.employee, "company")
        lc = frappe.get_value("Employee", leave_application.employee, "leave_cycle")
        ld = frappe.get_value("Leave Cycle", lc, "leave_days")
        wd = frappe.get_value("Leave Cycle", lc, "work_days")
        employee = frappe.get_doc("Employee", leave_application.employee)
        lwd = employee.ticket_entitlement_workdays
        tc = frappe.get_value("Ticket Sectors", employee.ticket_sector, "amount")
        account_ledger = ""
        cpt = ""
        ssta = frappe.get_value("Salary Structure Assignment", {"employee":leave_application.employee, "docstatus":"1"}, "salary_structure")
        sst = frappe.get_doc("Salary Structure", ssta)
        for item in sst.get("earnings"):
            #frappe.errprint(item.salary_component)
            #if item.salary_component == "Additional Dues":
            #    sc = frappe.get_doc("Salary Component", item.salary_component)
            #    for comp in sc.get("accounts"):
            #        if comp.company == company:
            #            account_ledger = comp.default_account
            #            cpt = item.salary_component
                
            #if item.salary_component == "Op.Additional Dues":
            #    sc = frappe.get_doc("Salary Component", item.salary_component)
            #    for comp in sc.get("accounts"):
            #        if comp.company == company:
            #            account_ledger = comp.default_account
            #            cpt = item.salary_component 

            if item.salary_component == "Leave Salary":
                sc = frappe.get_doc("Salary Component", "Leave Salary")
                for comp in sc.get("accounts"):
                    if comp.company == company:
                        account_ledger = comp.default_account
                        leave_cpt = item.salary_component 
            if item.salary_component == "Op.Leave Salary":
                sc = frappe.get_doc("Salary Component", "Op.Leave Salary")
                for comp in sc.get("accounts"):
                    if comp.company == company:
                        account_ledger = comp.default_account
                        leave_cpt = item.salary_component 
            if item.salary_component == "Staff Airfare":
                sc = frappe.get_doc("Salary Component", "Staff Airfare")
                for comp in sc.get("accounts"):
                    if comp.company == company:
                        account_ledger = comp.default_account
                        air_cpt = item.salary_component 
            if item.salary_component == "Op.Staff Airfare":
                sc = frappe.get_doc("Salary Component", "Op.Staff Airfare")
                for comp in sc.get("accounts"):
                    if comp.company == company:
                        account_ledger = comp.default_account
                        air_cpt = item.salary_component             



        #frappe.errprint(cpt) 

        ar = get_balance_on(frappe.get_value("Company", company, "default_ticket_payable_account"), leave_application.from_date, "Employee", leave_application.employee)
        ls = get_balance_on(frappe.get_value("Company", company, "default_leave_salary_payable"), leave_application.from_date, "Employee", leave_application.employee)                  

        if leave_application.include_all_leave_salary_and_airfare_dues_with_next_payment and leave_application.leave_type != "Leave Without Pay" and leave_application.leave_type != "Sick Leave":
            # pull all balances
        
            #frappe.errprint(ar)
            #frappe.errprint(ls)

            # create additional salary as per total

            # Leave Salary only
            if ((ls) * -1 ) > 0:
                sas = frappe.new_doc("Additional Salary")
                sas.payroll_date = leave_application.from_date
                sas.employee = leave_application.employee
                sas.salary_component = leave_cpt
                sas.amount = (ls) * -1
                sas.company = company
                sas.series = "HR-ADS-.YY.-.MM.-"
                sas.leave_application = leave_application.name
                sas.save(ignore_permissions=True)
                #sas.submit()

            # airticket only
            if ((ar) * -1 ) > 0:
                sas = frappe.new_doc("Additional Salary")
                sas.payroll_date = leave_application.from_date
                sas.employee = leave_application.employee
                sas.salary_component = air_cpt
                sas.amount = (ar) * -1
                sas.company = company
                sas.series = "HR-ADS-.YY.-.MM.-"
                sas.leave_application = leave_application.name
                sas.save(ignore_permissions=True)
                #sas.submit()    

                jv = frappe.new_doc("Journal Entry")
                jv.company = company
                jv.posting_date = leave_application.from_date
                #if salary_slip.company == ""
                if company == "National Engineering Services & Trading Co LLC":
                    jv.naming_series = "JV/HR/.YY./.####"
                if company == "NEST Employment Services LLC":
                    jv.naming_series = "NEE-JV/HR/.YY./.####"
                if company == "Firmo Technical Petroleum Services LLC":
                    jv.naming_series = "FIRMO-JV/HR/.YY./.####"        
                jv.voucher_type = "Journal Entry"
                if (ar + ls) > 0:
                    jv.append("accounts",{
                            "account": frappe.get_value("Company", company, "default_ticket_payable_account"),
                            "party_type":"Employee",
                            "party":leave_application.employee,
                            "debit_in_account_currency": ar,
                            #*******************************************************************************************************************************
                            # ADDED CODE
                            #*******************************************************************************************************************************
                            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                            "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                            "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                            "employee":salary_slip.employee,
                            "user_remark":leave_application.name
                            })
                    jv.append("accounts",{
                            "account": frappe.get_value("Company", company, "default_leave_salary_payable"),
                            "party_type":"Employee",
                            "party":leave_application.employee,
                            "debit_in_account_currency": ls,
                            #*******************************************************************************************************************************
                            # ADDED CODE
                            #*******************************************************************************************************************************
                            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                            "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                            "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                            "employee":salary_slip.employee,
                            "user_remark":leave_application.name
                            })        
                    jv.append("accounts",{
                            "account": account_ledger,
                            "credit_in_account_currency": (ar + ls),
                            #*******************************************************************************************************************************
                            # ADDED CODE
                            #*******************************************************************************************************************************
                            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                            "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                            "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                            "employee":salary_slip.employee,
                            "user_remark":leave_application.name
                            })
                    jv.leave_application = leave_application.name
                    jv.save(ignore_permissions=True)
        # if not collect all balances
        else:
            if leave_application.leave_type != "Sick Leave" and leave_application.leave_type != "Leave Without Pay":
                ssa_list = frappe.get_all("Salary Structure Assignment", filters={"employee": leave_application.employee}, fields=["name", "salary_structure"], order_by="creation desc")
                lsal = 0
                asal = 0
                
                sst = frappe.get_doc("Salary Structure", ssa_list[0].salary_structure)
                for item in sst.get("earnings"):
                    if frappe.get_value("Salary Component", item.salary_component, "include_in_leave_salary_provision") == 1:
                        lsal += item.amount
                    if frappe.get_value("Salary Component", item.salary_component, "include_in_airfare_provision") == 1:
                        asal += item.amount

                lscal = min(round((leave_application.total_leave_days / float(ld) * lsal) * 100) / 100, abs(ls))
                arcal = min(round((leave_application.total_leave_days / float(lwd)) * float(tc) * 100) / 100, abs(ar)) 

                
                #frappe.errprint(ld)
                #frappe.errprint(wd)
                #frappe.errprint(lsal)
                #frappe.errprint(wd)
                #frappe.errprint(ls)
                #frappe.errprint(ar)
                #frappe.errprint(arcal)
                #frappe.errprint(lscal)
                
                if (lscal) > 0:
                    sas = frappe.new_doc("Additional Salary")
                    sas.payroll_date = leave_application.from_date
                    sas.employee = leave_application.employee
                    sas.salary_component = leave_cpt
                    sas.amount = lscal
                    sas.company = company
                    sas.leave_application = leave_application.name
                    sas.overwrite_salary_structure_amount = 1
                    sas.series = "HR-ADS-.YY.-.MM.-"
                    sas.save(ignore_permissions=True)
                    sas.submit()

                    jv = frappe.new_doc("Journal Entry")
                    jv.company = company
                    jv.posting_date = leave_application.from_date
                    #if salary_slip.company == ""
                    if company == "National Engineering Services & Trading Co LLC":
                        jv.naming_series = "JV/HR/.YY./.####"
                    if company == "NEST Employment Services LLC":
                        jv.naming_series = "NEE-JV/HR/.YY./.####"
                    if company == "Firmo Technical Petroleum Services LLC":
                        jv.naming_series = "FIRMO-JV/HR/.YY./.####"        
                    jv.voucher_type = "Journal Entry"
                    if (lscal) > 0:
                        #jv.append("accounts",{
                        #        "account": frappe.get_value("Company", company, "default_ticket_payable_account"),
                        #        "party_type":"Employee",
                        #        "party":leave_application.employee,
                        #        "debit_in_account_currency": arcal,
                        #        })
                        jv.append("accounts",{
                                "account": frappe.get_value("Company", company, "default_leave_salary_payable"),
                                "party_type":"Employee",
                                "party":leave_application.employee,
                                "debit_in_account_currency": lscal
                                })        
                        jv.append("accounts",{
                                "account": account_ledger,
                                "credit_in_account_currency": lscal,
                                #*******************************************************************************************************************************
                                # ADDED CODE
                                #*******************************************************************************************************************************
                                "divisions": frappe.get_value("Department", frappe.get_value("Employee", leave_application.employee, "department"), "divisions"),
                                "department":frappe.get_value("Department", frappe.get_value("Employee", leave_application.employee, "department"), "department"),
                                "cost_center":frappe.get_value("Department", frappe.get_value("Employee", leave_application.employee, "department"), "cost_center"),
                                "employee":leave_application.employee,
                                "user_remark":leave_application.name
                                })
                        jv.leave_application = leave_application.name
                        jv.save(ignore_permissions=True)

                


#6/9
# This cancels the above Document if the SalarySlip is Cancelled.
def cancel_dues(leave_application, method):
    for item in frappe.get_all("Additional Salary", filters={"leave_application": leave_application.name}, fields=["name"]):
        a_s = frappe.get_doc("Additional Salary", item.name)
        a_s.cancel()

#7/9
# This method adds the monthly ACCRUALS for Leave Salary, Airticket Payable, and EOSB Payable for each employee. 
def add_benefits(salary_slip, method):
    emp_file = frappe.get_doc("Employee", salary_slip.employee)
    emp = frappe.get_doc("Employee", salary_slip.employee)
    leave_salary_comp = 0
    leave_salary = 0
    basic_ledger = ""
    basic = 0
    leave_ledger = ""
    airticket_ledger = ""
    eosb_ledger = ""
    #*******************************************************************************************************************************
    # ADDED CODE
    PFC = 0
    PFContribution = 0
    nest_cc = frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center")
    #nest_cc = frappe.get_value("Company", salary_slip.company, "cost_center")
    #*******************************************************************************************************************************
    jv = frappe.new_doc("Journal Entry")
    jv.company = salary_slip.company
    jv.posting_date = salary_slip.posting_date
    #if salary_slip.company == ""
    if salary_slip.company == "National Engineering Services & Trading Co LLC":
        jv.naming_series = "JV/HR/.YY./.####"
    if salary_slip.company == "NEST Employment Services LLC":
        jv.naming_series = "NEE-JV/HR/.YY./.####"
    if salary_slip.company == "Firmo Technical Petroleum Services LLC":
        jv.naming_series = "FIRMO-JV/HR/.YY./.####"        
    jv.voucher_type = "Journal Entry"
    sst = frappe.get_doc("Salary Structure", salary_slip.salary_structure)
    for item in sst.get("earnings"):
        if item.salary_component == "Leave Salary":
            ls = frappe.get_doc("Salary Component", "Leave Salary")
            for comp in ls.get("accounts"):
                if comp.company == salary_slip.company:
                    leave_ledger = comp.default_account
        if item.salary_component == "Op.Leave Salary":
            ls = frappe.get_doc("Salary Component", "Op.Leave Salary")
            for comp in ls.get("accounts"):
                if comp.company == salary_slip.company:
                    leave_ledger = comp.default_account
        if item.salary_component == "Staff Airfare":
            ls = frappe.get_doc("Salary Component", "Staff Airfare")
            for comp in ls.get("accounts"):
                if comp.company == salary_slip.company:
                    airticket_ledger = comp.default_account
        if item.salary_component == "Op.Staff Airfare":
            ls = frappe.get_doc("Salary Component", "Op.Staff Airfare")
            for comp in ls.get("accounts"):
                if comp.company == salary_slip.company:
                    airticket_ledger = comp.default_account
        if item.salary_component == "EOSB":
            ls = frappe.get_doc("Salary Component", "EOSB")
            for comp in ls.get("accounts"):
                if comp.company == salary_slip.company:
                    eosb_ledger = comp.default_account
        if item.salary_component == "Op.EOSB":
            ls = frappe.get_doc("Salary Component", "Op.EOSB")
            for comp in ls.get("accounts"):
                if comp.company == salary_slip.company:
                    eosb_ledger = comp.default_account     
    #frappe.errprint("start loop")
    #for item in sst.get("earnings"):
        #frappe.errprint(item.salary_component)
        if item.salary_component == "Basic":
            #frappe.errprint("inside loop")
            bdt = frappe.get_doc("Salary Component", "Basic")
            basic = item.amount
            for comp in bdt.get("accounts"):
                if comp.company == salary_slip.company:
                    basic_ledger = comp.default_account
        if item.salary_component == "Op.Basic":
            bdt = frappe.get_doc("Salary Component","Op.Basic")
            basic = item.amount
            for comp in bdt.get("accounts"):
                if comp.company == salary_slip.company:
                    basic_ledger = comp.default_account 
        #*******************************************************************************************************************************
        # ADDED CODE
        #*******************************************************************************************************************************
        if item.salary_component == "PF Contribution":
            ls = frappe.get_doc("Salary Component", "PF Contribution")
            PFContribution=item.amount
            PFC=1
            for comp in ls.get("accounts"):
                if comp.company == salary_slip.company:
                    PFContribution_ledger = comp.default_account
         #*******************************************************************************************************************************
                    
    #*******************************************************************************************************************************
    #ADDED CODE
    #*******************************************************************************************************************************                
    if PFC==1:
        pension_account = frappe.get_value("Company", salary_slip.company, "default_pension_payable_account") 
        jv.append("accounts",{
                "account":pension_account,
                "party_type":"Employee",
                "party":salary_slip.employee,
                "credit_in_account_currency": PFContribution,
                #*******************************************************************************************************************************
                # ADDED CODE
                #*******************************************************************************************************************************
                "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                "employee":salary_slip.employee,
                "user_remark":salary_slip.name
                })
        jv.append("accounts",{
                "account": PFContribution_ledger,
                "debit_in_account_currency": PFContribution,
                #*******************************************************************************************************************************
                #"cost_center" : nest_cc,
                # ADDED CODE
                #*******************************************************************************************************************************
                "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                "employee":salary_slip.employee,
                "user_remark":salary_slip.name
               })
        jv.salary_slip.name        
        jv.save()
    #*******************************************************************************************************************************                
                                   



    if emp_file.leave_salary:
        for item in salary_slip.get("earnings"):
            included = frappe.get_value("Salary Component", item.salary_component, "include_in_leave_salary_provision")
            if included:
                leave_salary_comp += item.amount
        leave_salary = leave_salary_comp * float(emp.leave_days) / float(emp.work_days)
        leave_salary_account = frappe.get_value("Company", salary_slip.company, "default_leave_salary_payable")
        jv.append("accounts",{
                "account":leave_salary_account,
                "party_type":"Employee",
                "party":salary_slip.employee,
                "credit_in_account_currency": leave_salary,
                #*******************************************************************************************************************************
                # ADDED CODE
                #*******************************************************************************************************************************
                "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                "employee":salary_slip.employee,
                "user_remark":salary_slip.name
                })  
        jv.append("accounts",{
                "account":leave_ledger,
                "debit_in_account_currency": leave_salary,
                #*******************************************************************************************************************************
                # ADDED CODE
                #*******************************************************************************************************************************
                "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                "employee":salary_slip.employee,
                "user_remark":salary_slip.name
                })
        jv.salary_slip.name        
        jv.save()        
    if emp_file.ticket_entitlement:
        ticket_value = frappe.get_value("Ticket Sectors", {"area":emp_file.ticket_sector}, "amount")
        ticket_monthly = ticket_value * float(salary_slip.payment_days) / float(emp_file.ticket_entitlement_workdays)
        ticket_account = frappe.get_value("Company", salary_slip.company, "default_ticket_payable_account") 
        jv.append("accounts",{
                "account":ticket_account,
                "party_type":"Employee",
                "party":salary_slip.employee,
                "credit_in_account_currency": ticket_monthly,
                #*******************************************************************************************************************************
                # ADDED CODE
                #*******************************************************************************************************************************
                "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                "employee":salary_slip.employee,
                "user_remark":salary_slip.name
                })
        jv.append("accounts",{
                "account": airticket_ledger,
                "debit_in_account_currency": ticket_monthly,
                #*******************************************************************************************************************************
                # ADDED CODE
                #*******************************************************************************************************************************
                "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                "employee":salary_slip.employee,
                "user_remark":salary_slip.name
                })
        jv.salary_slip.name        
        jv.save()
#*******************************************************************************************************************************
# FIELD emp.eosb DOES NOT EXIST ANY MORE!!!!!
#*******************************************************************************************************************************
    if emp.eosb_selection != "EOSB Not Entitled":
        eosb_account = frappe.get_value("Company", salary_slip.company, "default_eosb_payable_account")
        eosb_recv = frappe.get_value("Company", salary_slip.company, "default_eosb_receivable_account") 
        working_years = float(month_diff(salary_slip.posting_date, emp_file.date_of_joining)) / 12
        eosb = 0
        post_eosb = 0
        multiplier = 0

        #frappe.errprint((max(5, date_diff(salary_slip.posting_date, emp.date_of_joining)) - 5) * basic)
        if working_years < 3:
            multiplier = 1 / 3
        elif working_years < 5:
            multiplier = 2 / 3
        else:
            multiplier = 1        
        if working_years < 1:
            eosb = 0
        else:
            eosb = min(multiplier * (min(5, (date_diff(salary_slip.posting_date, emp_file.date_of_joining) / 365)) * basic * (12 / 365) * 21) 
            + ((max(5, (date_diff(salary_slip.posting_date, emp_file.date_of_joining) / 365)) - 5) * basic), 24 * basic)
            #frappe.errprint(basic)
       
        old_eosb = get_balance_on(eosb_account, salary_slip.posting_date, "Employee", salary_slip.employee)

        #frappe.errprint(old_eosb)

        old_eosb = abs(float(old_eosb))
      
        post_eosb = eosb - old_eosb
        
        #frappe.errprint(eosb)
        #frappe.errprint(old_eosb)
        #frappe.errprint(post_eosb)
                
        #if old_eosb:
        #    old_eosb_value = old_eosb[0].credit_in_account_currency
        #else:
        #    old_eosb_value = 0    
       
        jv.append("accounts",{
            "account":eosb_account,
            "party_type":"Employee",
            "party":salary_slip.employee,
            "credit_in_account_currency": post_eosb,
            #*******************************************************************************************************************************
            # ADDED CODE
            #*******************************************************************************************************************************
            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
            "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
            "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
            "employee":salary_slip.employee,
            "user_remark":salary_slip.name
            })
        jv.append("accounts",{
            "account": eosb_ledger,
            "debit_in_account_currency": post_eosb,
            #*******************************************************************************************************************************
            # ADDED CODE
            #*******************************************************************************************************************************
            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
            "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
            "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
            "employee":salary_slip.employee,
            "user_remark":salary_slip.name
            })
        jv.salary_slip.name    
        jv.save()
        
        if frappe.get_value("Employee", salary_slip.employee, "eosb_selection") == "EOSB Receivable":
            jv.append("accounts",{
                    "account":eosb_ledger,
                    "credit_in_account_currency": post_eosb,
                    #*******************************************************************************************************************************
                    # ADDED CODE
                    #*******************************************************************************************************************************
                    "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                    "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                    "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                    "employee":salary_slip.employee,
                    "user_remark":salary_slip.name
                    })
            jv.append("accounts",{
                    "account": eosb_recv,
                    "party_type":"Employee",
                    "party":salary_slip.employee,
                    "debit_in_account_currency": post_eosb,
                    #*******************************************************************************************************************************
                    # ADDED CODE
                    #*******************************************************************************************************************************
                    "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                    "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                    "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                    "employee":salary_slip.employee,
                    "user_remark":salary_slip.name
                    })
            jv.salary_slip.name        
            jv.save()

    #Inter Company
    o_comp = frappe.get_value("Employee", salary_slip.employee, "company")
    o_comp_doc = frappe.get_doc("Company",o_comp )
    s_comp = frappe.get_value("Employee", salary_slip.employee, "sponsoring_company")
    s_comp_doc = frappe.get_doc("Company", s_comp)
    #frappe.errprint("Company:")
    #frappe.errprint(s_comp)
    #frappe.errprint(o_comp)
    s_comp_ledger = ""
    salary_payable_ledger = frappe.get_value("Company",salary_slip.company, "default_payroll_payable_account")

    if salary_slip.company != s_comp:
        

        for item in o_comp_doc.get("related_parties_receivable_account"):
            if item.company == s_comp:
                s_comp_ledger = item.receivable_account


        jv.append("accounts",{
                    "account":salary_payable_ledger,
                    "credit_in_account_currency": salary_slip.net_pay,
                    "user_remark":salary_slip.name
                    })
        jv.append("accounts",{
                    "account": s_comp_ledger,
                    "party_type":"Employee",
                    "party":salary_slip.employee,
                    "debit_in_account_currency": salary_slip.net_pay,
                    #*******************************************************************************************************************************
                    # ADDED CODE
                    #*******************************************************************************************************************************
                    "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                    "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                    "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                    "employee":salary_slip.employee,
                    "user_remark":salary_slip.name
                    })
        jv.salary_slip.name            
        jv.save()


        #*******************************************************************************************************************************
        # THE ABOVE ENTRY IS SINGNLE SIDED.  THE PAYABLE ENTRY IS MISSING FROM THE ABOVE!!
        #*******************************************************************************************************************************
        


         #*******************************************************************************************************************************
        # THE ABOVE ENTRY IS SINGNLE SIDED.  THE PAYABLE ENTRY IS MISSING FROM THE ABOVE!!
        #*******************************************************************************************************************************


        o_comp_ledger = ""
        salary_payable_ledger = frappe.get_value("Company",frappe.get_value("Employee",salary_slip.employee, "sponsoring_company"), "default_payroll_payable_account")

        for item in s_comp_doc.get("related_parties_receivable_account"):
            if item.company == o_comp:
                o_comp_ledger = item.receivable_account

        jv = frappe.new_doc("Journal Entry")
        jv.company = frappe.get_value("Employee",salary_slip.employee, "sponsoring_company")
        jv.posting_date = salary_slip.posting_date
    #   if salary_slip.company == ""
        if frappe.get_value("Employee",salary_slip.employee, "sponsoring_company") == "National Engineering Services & Trading Co LLC":
            jv.naming_series = "JV/HR/.YY./.####"
        if frappe.get_value("Employee",salary_slip.employee, "sponsoring_company") == "NEST Employment Services LLC":
            jv.naming_series = "NEE-JV/HR/.YY./.####"
        if frappe.get_value("Employee",salary_slip.employee, "sponsoring_company") == "Firmo Technical Petroleum Services LLC":
            jv.naming_series = "FIRMO-JV/HR/.YY./.####"        
        jv.voucher_type = "Journal Entry"

        jv.append("accounts",{
                    "account":salary_payable_ledger,
                    "debit_in_account_currency": salary_slip.net_pay,
                    "party_type":"Employee",
                    "party":salary_slip.employee,
                    "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "divisions"),
                    "department":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "department"),
                    "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                    "employee":salary_slip.employee,
                    "user_remark":salary_slip.name
                    
                    })
        jv.append("accounts",{
                    "account": o_comp_ledger,
                    
                    "credit_in_account_currency": salary_slip.net_pay,
                    "user_remark":salary_slip.name
                    #*******************************************************************************************************************************
                    # ADDED CODE
                    #*******************************************************************************************************************************
                    
                    })
        jv.salary_slip.name            
        jv.save()
        #*********
    

    
    
    
    # Leave Allocation

#    if emp.leave_salary:
#        if emp.leave_cycle:
#            
#            lc = frappe.get_doc("Leave Cycle", emp.leave_cycle)
#            lc_month = int(salary_slip.start_date[5:7])
#            lc_month = str(lc_month)
#            for item in lc.get("monthly_leave"):
#                if item.month == lc_month:
#                    l_days = item.leaves
#            frappe.errprint(lc_month)
            #frappe.errprint(l_days)
            #l_days = round((salary_slip.payment_days / float(lc.work_days)) * float(lc.leave_days) * 2) / 2
#            la_list = frappe.get_all("Leave Ledger Entry", filters={"employee": emp.name,  "leave_type": "Annual Leave", "transaction_type":"Leave Allocation"}, fields=["transaction_name", "from_date", "to_date"], order_by="creation desc")
#            ll = frappe.new_doc("Leave Ledger Entry")
#            ll.employee = emp.name
#            ll.leave_type = "Annual Leave"
#            ll.transaction_type = "Leave Allocation"
#            ll.transaction_name = la_list[0].transaction_name
#            ll.from_date = la_list[0].from_date
#            ll.to_date = la_list[0].to_date
            #ll.leaves = l_days
            #ll.save()
#            frappe.errprint("Generated Leave Days") 
#            frappe.errprint(l_days)       

    salary_slip.calculate_net_pay()    


#8/9
# This adds the employees monthly Accrued Leave DAYS entry in the leave days ledger.
@frappe.whitelist()
def allocate_leave():
    for item in frappe.get_all("Employee", filters={"status": "Active",  "leave_salary": 1}, fields=["name"]):
        emp = frappe.get_doc("Employee", item.name)
        
        if emp.leave_cycle:
            frappe.errprint(emp.name)
            lc = frappe.get_doc("Leave Cycle", emp.leave_cycle)
            #lc_month = int(salary_slip.start_date[5:7])
            d = datetime.datetime.now()
            lc_month = d.strftime("%m")
            for item in lc.get("monthly_leave"):
                if item.month == lc_month:
                    l_days = item.leaves
            #frappe.errprint(lc_month)
            #frappe.errprint(l_days)
            l_days = round((31 / float(lc.work_days)) * float(lc.leave_days) * 2) / 2
            la_list = frappe.get_all("Leave Ledger Entry", filters={"employee": emp.name,  "leave_type": "Annual Leave", "transaction_type":"Leave Allocation"}, fields=["transaction_name", "from_date", "to_date"], order_by="creation desc")
            #if emp.name != "2009":
            if la_list:
                ll = frappe.new_doc("Leave Ledger Entry")
                ll.employee = emp.name
                ll.leave_type = "Annual Leave"
                ll.transaction_type = "Leave Allocation"
                ll.transaction_name = la_list[0].transaction_name
                ll.from_date = la_list[0].from_date
                ll.to_date = la_list[0].to_date
                ll.leaves = l_days
                ll.save()
                frappe.errprint("Generated Leave Days")
                frappe.errprint(emp.name) 
                frappe.errprint(l_days)  


#9/9
# This adds an absent day entry for each day until an employee returns from Leave.
def mark_absent(leave_application, method):

    dd = add_days(today(), -1)
    for item in frappe.get_all("Leave Application", filters={"docstatus":1, "to_date":("<", dd)  ,"duty_resumption_date":("=", "")}, fields=["name", "modified", "employee", "to_date", "employee_name"]):
        attendance = frappe.get_doc(dict(doctype='Attendance', employee=item.employee, employee_name=item.employee_name, attendance_date=today(), status="Absent", company=frappe.get_value("Employee", item.employee, "Company")))
        attendance.insert()
        attendance.submit()
        #frappe.errprint(item.name) 

    
    
    for item in frappe.get_all("Leave Application", filters={"modified": (">=", dd), "docstatus":1, "duty_resumption_date":("!=", "")}, fields=["name", "modified", "employee", "to_date", "employee_name", "duty_resumption_date"]):
        #frappe.errprint(item.modified.date())
        #frappe.errprint(item.name)
        emp = frappe.get_doc("Employee", item.employee)
        s_date = item.duty_resumption_date
        p_date = add_days(item.duty_resumption_date, -1)
        

        while s_date < dd:
            att_name = frappe.get_value("Attendance", {"employee":item.employee, "attendance_date":s_date}, "name")
            attendance = frappe.get_doc("Attendance", att_name)
            attendance.cancel()
            s_date = add_days(s_date, 1)

        h_list = frappe.get_doc("Employee", item.employee, "holiday_list")
        while p_date > item.to_date :
            if frappe.db.sql("""SELECT holiday_date from `tabHoliday` where parent = %s""",(h_list)):
                att_name = frappe.get_value("Attendance", {"employee":item.employee, "attendance_date":p_date}, "name")
                attendance = frappe.get_doc("Attendance", att_name)
                attendance.cancel()
                p_date = add_days(p_date, -1)
            
 




#def mark_absent():
#    if frappe.get_all("Leave Application", filters={"from_date": (">", "01-03-2021"), "docstatus": "1", "leave_type":"Annual Leave", "to_date":(">", today()), "duty_resumption_date":""}, fields=["name"]):
#        for la in frappe.get_all("Leave Application", filters={"from_date": (">", "01-03-2021"), "docstatus": "1", "leave_type":"Annual Leave", "to_date":(">", today()), "duty_resumption_date":""}, fields=["name"]):
#            lapp = frappe.get_doc("Leave Application", la.name)
#            attendance = frappe.get_doc(dict(doctype='Attendance', employee=lapp.employee, employee_name=lapp.employee_name, attendance_date=today(), status="Absent", company=frappe.get_value("Employee", lapp.employee, "Company")))
#            attendance.insert()
#            attendance.submit()    

# s_date = 16-03-2021            
# last_date = 15-03-2021 - 16
# duty_resumption = 21-03-2021
# today = 28-03-2021
        
                       

    