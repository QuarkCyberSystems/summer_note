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

# 1/13
# This method adds "Additional Salary" Document as "OT1" and "OT2" SalarySlip components
# which is pulled during Payroll Processing, for the OT1 and OT2 Hours Submitted.
# The OT1 & OT2 are calculated based on Basic Salary Only.
# ********  Timesheet - On Submit  ********
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
        sas.payroll_date = timesheet.date   # Payroll Date on the TS Page
        sas.employee = timesheet.employee
        sas.salary_component = "OT1"
        sas.amount = ot1
        sas.company = timesheet.company
        sas.series = "HR-ADS-.YY.-.MM.-"
        sas.timesheet = timesheet.name
        sas.save()
        sas.submit()

    if ot2 > 0:
        sas = frappe.new_doc("Additional Salary")
        sas.payroll_date = timesheet.date # Payroll Date on the TS Page
        sas.employee = timesheet.employee
        sas.salary_component = "OT2"
        sas.amount = ot2
        sas.company = timesheet.company
        sas.series = "HR-ADS-.YY.-.MM.-"
        sas.timesheet = timesheet.name
        sas.save()
        sas.submit()

#2/13
# This cancels the above "Additional Salary" Document if the "SalarySlip" is Cancelled.
# ********  Leave Application - On Cancel  ********
def cancel_dues(leave_application, method):
    for item in frappe.get_all("Additional Salary", filters={"leave_application": leave_application.name}, fields=["name"]):
        a_s = frappe.get_doc("Additional Salary", item.name)
        a_s.cancel()
        a_s.delete()

    for item in frappe.get_all("Journal Entry", filters={"leave_application": leave_application.name}, fields=["name"]):
        a_s = frappe.get_doc("Journal Entry", item.name)
        a_s.cancel()
        a_s.delete()

#3/13
# This code adds an "Expense Claim" Entry under PAYROLL CONTROL Account, to be reversed during Posting/Submission of Payroll Slips.
# The standard functionality of ERPNext will add an Additional Salary Entry once an "Expense Claim" has been Submitted.
# ********  Salary Slip - after_insert  ********
def add_expense_claim(salary_slip, method):
    #emp = salary_slip.employee
    frappe.errprint ('******** 3 ADD EXPENSE CLAIMS ********')
    if salary_slip.expense_claim_added == 0:
        exp_claim =  frappe.get_all('Expense Claim', filters={
                'status': 'Unpaid',
                'employee': salary_slip.employee,
                'docstatus':1,
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
            frappe.set_value('Expense Claim', item.name, 'status', 'Paid')
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
        frappe.errprint('3. add_expense_claim Cost Center - ' + nest_cc)
        #nest_cc = frappe.get_value("Company", salary_slip.company, "cost_center")
        #*******************************************************************************************************************************
        salary_exp_account = frappe.get_value("Company", salary_slip.company, "default_payroll_payable_account")
        exp_account = frappe.get_value("Company", salary_slip.company, "default_expense_claim_payable_account")
        pay_control = frappe.get_value("Company", salary_slip.company, "payroll_controll")

        jv = frappe.new_doc("Journal Entry")
        jv.company = salary_slip.company
        jv.posting_date = salary_slip.posting_date
        jv.title = salary_slip.name + " Expense Claims: " + salary_slip.start_date
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
                    "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                    "department":frappe.get_value("Employee", salary_slip.employee, "department"),
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
                    "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                    "department":frappe.get_value("Employee", salary_slip.employee, "department"),
                    "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                    "employee":salary_slip.employee,
                    "user_remark": claims
                  })

            jv.salary_slip = salary_slip.name
            jv.save()
            jv.submit()

        salary_slip.calculate_net_pay()
        salary_slip.save()

#4/13
# This method adds the monthly ACCRUALS for Leave Salary, Airticket, EOSB, and Pension Payable for each employee. 
# ********  Salary Slip - after_insert  ********
def add_benefits(salary_slip, method):
    frappe.errprint ('******** 4 ADD BENIFITS ********')

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
    jv.title = salary_slip.name + " Accruals: " + salary_slip.start_date
    jv.company = salary_slip.company
    jv.posting_date = salary_slip.posting_date

    if salary_slip.company == "National Engineering Services & Trading Co LLC":
        jv.naming_series = "JV/HR/.YY./.####"
    if salary_slip.company == "NEST Employment Services LLC":
        jv.naming_series = "NEE-JV/HR/.YY./.####"
    if salary_slip.company == "Firmo Technical Petroleum Services LLC":
        jv.naming_series = "FIRMO-JV/HR/.YY./.####"
    jv.voucher_type = "Journal Entry"
    sst = frappe.get_doc("Salary Structure", salary_slip.salary_structure)
    PFC= sst.pension_amount
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
        if item.salary_component == "Basic":
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
 
    frappe.errprint('4. add_benefits Cost Center - ' + frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"))

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
                "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                "department":frappe.get_value("Employee", salary_slip.employee, "department"),
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
                "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                "department":frappe.get_value("Employee", salary_slip.employee, "department"),
                "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                "employee":salary_slip.employee,
                "user_remark":salary_slip.name
                })
        jv.salary_slip = salary_slip.name
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
                "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                "department":frappe.get_value("Employee", salary_slip.employee, "department"),
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
                "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                "department":frappe.get_value("Employee", salary_slip.employee, "department"),
                "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                "employee":salary_slip.employee,
                "user_remark":salary_slip.name
                })
        jv.salary_slip = salary_slip.name
        jv.save()


    if emp.eosb_selection != "EOSB Not Entitled":
        eosb_account = frappe.get_value("Company", salary_slip.company, "default_eosb_payable_account")
        eosb_recv = frappe.get_value("Company", salary_slip.company, "default_eosb_receivable_account") 
        working_years = float(month_diff(salary_slip.posting_date, emp_file.date_of_joining)) / 12
        eosb = 0
        post_eosb = 0
        multiplier = 0

        if working_years < 3:
            multiplier = 1 / 3
        elif working_years < 5:
            multiplier = 2 / 3
        else:
            multiplier = 1

        if working_years < 1:
            eosb = 0
        else:
            eosb = min(multiplier * (min(5, (date_diff(salary_slip.end_date, emp_file.date_of_joining) / 365)) * basic * (12 / 365) * 21) 
            + ((max(5, (date_diff(salary_slip.end_date, emp_file.date_of_joining) / 365)) - 5) * basic), 24 * basic)

        old_eosb = get_balance_on(eosb_account, salary_slip.end_date, "Employee", salary_slip.employee)
        old_eosb = abs(float(old_eosb))
        #frappe.errprint(old_eosb)
        #frappe.errprint(eosb)
        post_eosb = eosb - old_eosb

        jv.append("accounts",{
            "account":eosb_account,
            "party_type":"Employee",
            "party":salary_slip.employee,
            "credit_in_account_currency": post_eosb,
            #*******************************************************************************************************************************
            # ADDED CODE
            #*******************************************************************************************************************************
            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
            "department":frappe.get_value("Employee", salary_slip.employee, "department"),
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
            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
            "department":frappe.get_value("Employee", salary_slip.employee, "department"),
            "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
            "employee":salary_slip.employee,
            "user_remark":salary_slip.name
            })
        jv.salary_slip = salary_slip.name
        jv.save()
        
        if frappe.get_value("Employee", salary_slip.employee, "eosb_selection") == "EOSB Receivable":
            jv.append("accounts",{
                    "account":eosb_ledger,
                    "credit_in_account_currency": post_eosb,
                    #*******************************************************************************************************************************
                    # ADDED CODE
                    #*******************************************************************************************************************************
                    "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                    "department":frappe.get_value("Employee", salary_slip.employee, "department"),
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
                    "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                    "department":frappe.get_value("Employee", salary_slip.employee, "department"),
                    "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                    "employee":salary_slip.employee,
                    "user_remark":salary_slip.name
                    })
            jv.salary_slip = salary_slip.name
            jv.save()
    
    #*******************************************************************************************************************************
    #ADDED CODE
    #*******************************************************************************************************************************                
    if PFC>0:
        pension_payable = frappe.get_value("Company", salary_slip.company, "default_pension_payable_account")
        pension_expense = frappe.get_value("Company", salary_slip.company, "default_pension_expense_account")
        jv.append("accounts",{
                "account":pension_payable,
                "party_type":"Employee",
                "party":salary_slip.employee,
                "credit_in_account_currency": PFC,
                #*******************************************************************************************************************************
                # ADDED CODE
                #*******************************************************************************************************************************
                "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                "department":frappe.get_value("Employee", salary_slip.employee, "department"),
                "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                "employee":salary_slip.employee,
                "user_remark":salary_slip.name
                })
        jv.append("accounts",{
                "account": pension_expense,
                "debit_in_account_currency": PFC,
                #*******************************************************************************************************************************
                #"cost_center" : nest_cc,
                # ADDED CODE
                #*******************************************************************************************************************************
                "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                "department":frappe.get_value("Employee", salary_slip.employee, "department"),
                "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                "employee":salary_slip.employee,
                "user_remark":salary_slip.name
               })
        jv.salary_slip = salary_slip.name
        jv.save()
    #*******************************************************************************************************************************
    jv.submit()

    salary_slip.calculate_net_pay()

#5/13
# This method adds a "Additional Salary" document as "Additional Dues" Salary Component into the "SalarySlip" against "LEAVE APPLICATIONs" Taken by the employee.
# It depends on the Annual Leave days taken and selection of flag in the Leave application to include_all_leave_salary_and_airfare_dues_with_next_payment.
# ********  Salary Slip - after_insert  ********
def add_dues(salary_slip, method):
    
    frappe.errprint ('******** 5 ADD DUES ********')
    frappe.errprint(salary_slip.employee)
    la_list = frappe.get_all('Leave Application', filters={
                'status': 'Approved',
                'leave_type': 'Annual Leave',
                'employee': salary_slip.employee,
                'docstatus':1,
                'salary_slip':'',
                'from_date': ['between', [salary_slip.start_date, salary_slip.end_date]]
                #'from_date': ['>=', salary_slip.start_date], # *******************************************************************************************************
                #'from_date': ['<=', salary_slip.end_date]
            }, fields=['name'])
    frappe.errprint(la_list)        

    frappe.errprint('Leave Applications Start Date: ' + str(salary_slip.start_date)) # ****************************************************************************************
    frappe.errprint('Leave Applications End Date: ' + str(salary_slip.end_date))  # *******************************************************************************************
    frappe.errprint('Leave Applications Found: ' + str(len(la_list))) # *******************************************************************************************************

   
    for la_item in la_list:
        frappe.errprint('Processing Leave Application: ' + str(la_item.name))  # **********************************************************************************************
        leave_application = frappe.get_doc("Leave Application", la_item.name)
        company = frappe.get_value("Employee", leave_application.employee, "company")
        frappe.errprint('EMPLOYEE COMPANY: ' + company) 
        lc = frappe.get_value("Employee", leave_application.employee, "leave_cycle")
        ld = frappe.get_value("Leave Cycle", lc, "leave_days")
        wd = frappe.get_value("Leave Cycle", lc, "work_days")
        employee = frappe.get_doc("Employee", leave_application.employee)
        lwd = employee.ticket_entitlement_workdays
        tc = frappe.get_value("Ticket Sectors", employee.ticket_sector, "amount")
        # TWO DIFFERENT ACCOUNTS!!
        #account_ledger = ""
        ls_account_ledger = ""
        ar_account_ledger = ""
        cpt = ""
        ssta = frappe.get_value("Salary Structure Assignment", {"employee":leave_application.employee, "docstatus":"1"}, "salary_structure")
        sst = frappe.get_doc("Salary Structure", ssta)

        for item in sst.get("earnings"):
            if item.salary_component == "Leave Salary":
                sc = frappe.get_doc("Salary Component", "Leave Salary")
                for comp in sc.get("accounts"):
                    if comp.company == company:
                        ls_account_ledger = comp.default_account
                        leave_cpt = item.salary_component 
            if item.salary_component == "Op.Leave Salary":
                sc = frappe.get_doc("Salary Component", "Op.Leave Salary")
                for comp in sc.get("accounts"):
                    if comp.company == company:
                        ls_account_ledger = comp.default_account
                        leave_cpt = item.salary_component 
            if item.salary_component == "Staff Airfare":
                sc = frappe.get_doc("Salary Component", "Staff Airfare")
                for comp in sc.get("accounts"):
                    if comp.company == company:
                        ar_account_ledger = comp.default_account
                        air_cpt = item.salary_component 
            if item.salary_component == "Op.Staff Airfare":
                sc = frappe.get_doc("Salary Component", "Op.Staff Airfare")
                for comp in sc.get("accounts"):
                    if comp.company == company:
                        ar_account_ledger = comp.default_account
                        air_cpt = item.salary_component

        ar = get_balance_on(frappe.get_value("Company", company, "default_ticket_payable_account"), leave_application.from_date, "Employee", leave_application.employee)
        ls = get_balance_on(frappe.get_value("Company", company, "default_leave_salary_payable"), leave_application.from_date, "Employee", leave_application.employee)                  
        frappe.errprint(str(leave_application.include_all_leave_salary_and_airfare_dues_with_next_payment))
        frappe.errprint(leave_application.leave_type)
        #if leave_application.include_all_leave_salary_and_airfare_dues_with_next_payment and leave_application.leave_type != "Leave Without Pay" and leave_application.leave_type != "Sick Leave":
        #if str(leave_application.include_all_leave_salary_and_airfare_dues_with_next_payment) == '1' and leave_application.leave_type == "Annual Leave":
        if leave_application.include_all_leave_salary_and_airfare_dues_with_next_payment and leave_application.leave_type == "Annual Leave":
            frappe.errprint ('INSIDE LONG LEAVE')
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
                sas.salary_slip = salary_slip.name
                sas.save(ignore_permissions=True)
                sas.submit()

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
                sas.salary_slip = salary_slip.name
                sas.save(ignore_permissions=True)
                sas.submit()

            if ((ar + ls) * -1) > 0:
                jv = frappe.new_doc("Journal Entry")
                jv.company = company
                jv.posting_date = leave_application.from_date
                jv.title = salary_slip.name + " Leave Salary: " + salary_slip.start_date
                if company == "National Engineering Services & Trading Co LLC":
                    jv.naming_series = "JV/HR/.YY./.####"
                if company == "NEST Employment Services LLC":
                    jv.naming_series = "NEE-JV/HR/.YY./.####"
                if company == "Firmo Technical Petroleum Services LLC":
                    jv.naming_series = "FIRMO-JV/HR/.YY./.####"
                jv.voucher_type = "Journal Entry"
            
                jv.append("accounts",{
                        "account": frappe.get_value("Company", company, "default_leave_salary_payable"),
                        "party_type":"Employee",
                        "party":leave_application.employee,
                        "debit_in_account_currency": ls,
                        #*******************************************************************************************************************************
                        # ADDED CODE
                        #*******************************************************************************************************************************
                        "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                        "department":frappe.get_value("Employee", salary_slip.employee, "department"),
                        "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                        "employee":salary_slip.employee,
                        "user_remark":leave_application.name
                        })
                jv.append("accounts",{
                        #"account": frappe.get_value("Company", company, "default_payroll_payable_account"),
                        "account": ls_account_ledger,
                        "credit_in_account_currency": ls,
                        #*******************************************************************************************************************************
                        # ADDED CODE
                        #*******************************************************************************************************************************
                        "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                        "department":frappe.get_value("Employee", salary_slip.employee, "department"),
                        "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                        "employee":salary_slip.employee,
                        "user_remark":leave_application.name
                        })
                jv.append("accounts",{
                        "account": frappe.get_value("Company", company, "default_ticket_payable_account"),
                        "party_type":"Employee",
                        "party":leave_application.employee,
                        "debit_in_account_currency": ar,
                        #*******************************************************************************************************************************
                        # ADDED CODE
                        #*******************************************************************************************************************************
                        "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                        "department":frappe.get_value("Employee", salary_slip.employee, "department"),
                        "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                        "employee":salary_slip.employee,
                        "user_remark":leave_application.name
                        })
                jv.append("accounts",{
                        #"account": frappe.get_value("Company", company, "default_payroll_payable_account"),
                        "account": ar_account_ledger,
                        "credit_in_account_currency": ar,
                        #*******************************************************************************************************************************
                        # ADDED CODE
                        #*******************************************************************************************************************************
                        "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                        "department":frappe.get_value("Employee", salary_slip.employee, "department"),
                        "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                        "employee":salary_slip.employee,
                        "user_remark":leave_application.name
                        })
                jv.leave_application = leave_application.name
                jv.salary_slip = salary_slip.name
                jv.save(ignore_permissions=True)
                jv.submit()

                #leave Application being set with salary slip
            frappe.errprint("Full Leave: Adding to Leave Application " + str(leave_application.name) + " a salary_slip " + str(salary_slip.name))
            frappe.set_value("Leave Application", leave_application.name, "salary_slip", salary_slip.name)


        # if not collect all balances
        else:
            #if leave_application.leave_type != "Sick Leave" and leave_application.leave_type != "Leave Without Pay":
            if leave_application.leave_type == "Annual Leave":
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

                if (lscal) > 0:
                    sas = frappe.new_doc("Additional Salary")
                    sas.payroll_date = leave_application.from_date
                    sas.employee = leave_application.employee
                    sas.salary_component = leave_cpt
                    sas.amount = lscal
                    sas.company = company
                    sas.leave_application = leave_application.name
                    sas.salary_slip = salary_slip.name
                    sas.overwrite_salary_structure_amount = 1
                    sas.series = "HR-ADS-.YY.-.MM.-"
                    sas.save(ignore_permissions=True)
                    sas.submit()

                    # ***************************************************            ************************************                 **********************************
                    frappe.errprint(leave_application.employee)
                    frappe.errprint(frappe.get_value("Employee", leave_application.employee, "department"))
                    frappe.errprint(frappe.get_value("Department", frappe.get_value("Employee", leave_application.employee, "department"), "cost_center"))

                    jv = frappe.new_doc("Journal Entry")
                    jv.company = company
                    jv.posting_date = leave_application.from_date
                    jv.title = salary_slip.name + " Leave Salary: " + salary_slip.start_date
                    if company == "National Engineering Services & Trading Co LLC":
                        jv.naming_series = "JV/HR/.YY./.####"
                    if company == "NEST Employment Services LLC":
                        jv.naming_series = "NEE-JV/HR/.YY./.####"
                    if company == "Firmo Technical Petroleum Services LLC":
                        jv.naming_series = "FIRMO-JV/HR/.YY./.####"
                    jv.voucher_type = "Journal Entry"
                    if (lscal) > 0:
                        jv.append("accounts",{
                                "account": frappe.get_value("Company", company, "default_leave_salary_payable"),
                                "party_type":"Employee",
                                "party":leave_application.employee,
                                "debit_in_account_currency": lscal
                                })        
                        jv.append("accounts",{
                                "account": ls_account_ledger,
                                "credit_in_account_currency": lscal,
                                #*******************************************************************************************************************************
                                # ADDED CODE
                                #*******************************************************************************************************************************
                                "divisions": frappe.get_value("Department", frappe.get_value("Employee", leave_application.employee, "department"), "division"),
                                "department":frappe.get_value("Employee", leave_application.employee, "department"),
                                "cost_center":frappe.get_value("Department", frappe.get_value("Employee", leave_application.employee, "department"), "cost_center"),
                                "employee":leave_application.employee,
                                "user_remark":leave_application.name
                                })
                        jv.leave_application = leave_application.name
                        jv.salary_slip = salary_slip.name
                        jv.save(ignore_permissions=True)
                        jv.submit()
                        #leave Application being set with salary slip
                        frappe.errprint("Short Leave: Adding to Leave Application " + str(leave_application.name) + " a salary_slip " + str(salary_slip.name))
                        frappe.set_value("Leave Application", leave_application.name, "salary_slip", salary_slip.name)

    #Inter Company
    jv = frappe.new_doc("Journal Entry")
    jv.title = salary_slip.name + " Inter Company: " + salary_slip.start_date
    jv.company = salary_slip.company
    jv.posting_date = salary_slip.posting_date
    if frappe.get_value("Employee",salary_slip.employee, "sponsoring_company") == "National Engineering Services & Trading Co LLC":
        jv.naming_series = "JV/HR/.YY./.####"
    if frappe.get_value("Employee",salary_slip.employee, "sponsoring_company") == "NEST Employment Services LLC":
        jv.naming_series = "NEE-JV/HR/.YY./.####"
    if frappe.get_value("Employee",salary_slip.employee, "sponsoring_company") == "Firmo Technical Petroleum Services LLC":
        jv.naming_series = "FIRMO-JV/HR/.YY./.####"
    jv.voucher_type = "Journal Entry"
    o_comp = frappe.get_value("Employee", salary_slip.employee, "company")
    o_comp_doc = frappe.get_doc("Company",o_comp )
    s_comp = frappe.get_value("Employee", salary_slip.employee, "sponsoring_company")
    s_comp_doc = frappe.get_doc("Company", s_comp)
    s_comp_ledger = "" #**********************************************************************************************     MISSING !!!!    ***********************************
    salary_payable_ledger = frappe.get_value("Company",salary_slip.company, "default_payroll_payable_account")

    if salary_slip.company != s_comp:
        frappe.errprint("Company Comparison")
        for item in o_comp_doc.get("related_parties_receivable_account"):
            if item.company == s_comp:
                s_comp_ledger = item.receivable_account

        jv.append("accounts",{
                    "account": s_comp_ledger,
                    "credit_in_account_currency": salary_slip.net_pay,
                    "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                    "department":frappe.get_value("Employee", salary_slip.employee, "department"),
                    "cost_center":frappe.get_value("Company", frappe.get_value("Employee",salary_slip.employee, "company"), "cost_center"),
                    "user_remark":salary_slip.name
                    })
        jv.append("accounts",{
                    "account": salary_payable_ledger,
                    "party_type":"Employee",
                    "party":salary_slip.employee,
                    "debit_in_account_currency": salary_slip.net_pay,
                    #*******************************************************************************************************************************
                    # ADDED CODE
                    #*******************************************************************************************************************************
                    "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
                    "department":frappe.get_value("Employee", salary_slip.employee, "department"),
                    "cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
                    "employee":salary_slip.employee,
                    "user_remark":salary_slip.name
                    })
        jv.salary_slip = salary_slip.name
        jv.save()
        jv.submit()

        #o_comp_ledger = "" #**********************************************************************************************     MISSING !!!!    ***********************************
        #salary_payable_ledger = frappe.get_value("Company",frappe.get_value("Employee",salary_slip.employee, "sponsoring_company"), "default_payroll_payable_account")

        #for item in s_comp_doc.get("related_parties_receivable_account"):
        #    if item.company == o_comp:
        #        o_comp_ledger = item.receivable_account

        #jv = frappe.new_doc("Journal Entry")
        #jv.title = salary_slip.name + " Inter Company: " + salary_slip.start_date
        #jv.company = frappe.get_value("Employee",salary_slip.employee, "sponsoring_company")
        #jv.posting_date = salary_slip.posting_date
        #if frappe.get_value("Employee",salary_slip.employee, "sponsoring_company") == "National Engineering Services & Trading Co LLC":
        #    jv.naming_series = "JV/HR/.YY./.####"
        #if frappe.get_value("Employee",salary_slip.employee, "sponsoring_company") == "NEST Employment Services LLC":
        #    jv.naming_series = "NEE-JV/HR/.YY./.####"
        #if frappe.get_value("Employee",salary_slip.employee, "sponsoring_company") == "Firmo Technical Petroleum Services LLC":
        #    jv.naming_series = "FIRMO-JV/HR/.YY./.####"
        #jv.voucher_type = "Journal Entry"

        #jv.append("accounts",{
        #           "account":o_comp_ledger,
        #            "debit_in_account_currency": salary_slip.net_pay,
        #            "party_type":"Employee",
        #            "party":salary_slip.employee,
        #            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
        #            "department":frappe.get_value("Employee", salary_slip.employee, "department"),
        #            "cost_center":frappe.get_value("Company", frappe.get_value("Employee",salary_slip.employee, "sponsoring_company"), "cost_center"),
        #            "employee":salary_slip.employee,
        #            "user_remark":salary_slip.name
        #           
        #            })
        #jv.append("accounts",{
        #            "account": salary_payable_ledger,
        #            "credit_in_account_currency": salary_slip.net_pay,
        #            "divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
        #            "department":frappe.get_value("Employee", salary_slip.employee, "department"),
        #            "cost_center":frappe.get_value("Company", frappe.get_value("Employee",salary_slip.employee, "sponsoring_company"), "cost_center"),
        #            "user_remark":salary_slip.name
        #            })
        #jv.salary_slip = salary_slip.name
        #jv.save()
        ##jv.submit()

    salary_slip.calculate_net_pay()
    salary_slip.save()
    salary_slip.reload()

#6/13
# This adds the employees monthly Accrued Leave DAYS entry in the leave days ledger.
# ********  Salary Slip - after_insert  ********
@frappe.whitelist()  # WHY whitelist it?? 
def allocate_leave(salary_slip, method):
    for item in frappe.get_all("Employee", filters={"status": "Active",  "leave_salary": 1, "Employee": salary_slip.employee}, fields=["name"]): # FIXED NOW *********************   ALL EMPLOYEES !!!    *******************
        emp = frappe.get_doc("Employee", item.name)
        mldays = 0
        if emp.leave_cycle:
            frappe.errprint(emp.name)
            lc = frappe.get_doc("Leave Cycle", emp.leave_cycle)
            #*******************************************************************************************************************************
            # CHANGED 'item' below to 'item1' not to conflict with 'item' in the above loop
            #******************************************************************************************
            d = str(salary_slip.start_date) # datetime.now()
            lc_month = d[5:7] #d.strftime("%m")
            frappe.errprint (d)
            frappe.errprint (lc_month)
            for iteml in lc.get("monthly_leave"):
                if int(iteml.month) == int(lc_month):
                    mldays = iteml.leaves
            l_days = round((float(salary_slip.payment_days) / float(salary_slip.total_working_days)) * float(mldays) * 2) / 2
            la_list = frappe.get_all("Leave Ledger Entry", filters={
                "employee": emp.name,  
                "leave_type": "Annual Leave", 
                "transaction_type":"Leave Allocation"
                }, fields=["transaction_name", "from_date", "to_date"], order_by="creation desc")
            if la_list:
                ll = frappe.new_doc("Leave Ledger Entry")
                ll.employee = emp.name
                ll.leave_type = "Annual Leave"
                ll.transaction_type = "Leave Allocation"
                ll.transaction_name = la_list[0].transaction_name       #       **************************   WHY THIS ????? *********************
                ll.salary_slip = salary_slip.name
                ll.from_date = la_list[0].from_date                     #       **************************   WHY THIS ????? *********************
                ll.to_date = la_list[0].to_date                         #       **************************   WHY THIS ????? *********************
                ll.leaves = l_days
                ll.save()
                #ll.submit()            SHOULD BE SUBMITTED AT SALARY PAYMENT,,,,!

            #frappe.errprint("mldays " + str(mldays))
            #frappe.errprint("payment days " + str(salary_slip.payment_days))
            #frappe.errprint("Total Working days " + str(salary_slip.total_working_days))
            #frappe.errprint("Generated Leave Days")
            #frappe.errprint(emp.name)
            #frappe.errprint(l_days)

#7/13
# This code cancels and Unmarks the "Expense Claim" and "Leave Application" documents if the "SalarySlip" is Cancelled.
# ********  Salary Slip - On Cancel  ********
def cancel_salary_slip(salary_slip, method):
    for item in frappe.get_all("Expense Claim", filters={"salary_slip": salary_slip.name}, fields=["name"]):
        frappe.errprint('Unmark: Found Expense Claim ' + str(item.name)) #*********************************************************************************************************************
        frappe.set_value("Expense Claim", item.name, "salary_slip", "")
        frappe.set_value("Expense Claim", item.name, "status", "Unpaid")

    for item in frappe.get_all("Leave Application", filters={"salary_slip": salary_slip.name}, fields=["name"]):
        frappe.errprint('Unmark: Found Leave Application ' + str(item.name)) #*********************************************************************************************************************
        frappe.set_value("Leave Application", item.name, "salary_slip", "")
        for item1 in frappe.get_all("Additional Salary", filters={"leave_application": item.name}, fields=["name"]):
            frappe.errprint('Delete: Found LA Additional Salaries ' + str(item1.name)) #*********************************************************************************************************************
            a_s=frappe.get_doc("Additional Salary", item1.name)
            a_s.cancel()
            a_s.delete()

    for item in frappe.get_all("Journal Entry", filters={"salary_slip": salary_slip.name}, fields=["name"]):
        frappe.errprint('Delete: Found JV ' + str(item.name)) #*********************************************************************************************************************
        jv=frappe.get_doc("Journal Entry", item.name)
        jv.cancel()
        jv.delete()

    for item in frappe.get_all("Additional Salary", filters={"salary_slip": salary_slip.name}, fields=["name"]):
        frappe.errprint('Delete: Found AdditionalSalaries ' + str(item.name)) #*********************************************************************************************************************
        a_s=frappe.get_doc("Additional Salary", item.name)
        a_s.cancel()
        a_s.delete()
    
    for item in frappe.get_all("Leave Ledger Entry", filters={
        "salary_slip": salary_slip.name, 
        'docstatus':0
        }, fields=["name"]):
        frappe.errprint('Delete: Found Leave Ledger Entries ' + str(item.name)) #*********************************************************************************************************************
        ll=frappe.get_doc("Leave Ledger Entry", item.name)
        #ll.cancel()
        ll.delete()

# 8/13
# This adds a Project agaist Every SO except for Engineering Sertvices and Vendor Projects.
# ********  Sales Order - Before Submit  ********
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

#9/13
# This adds an absent day entry for each day until an employee returns from Leave.
# ********  Scheduler events - Daily  ********
def mark_absent(leave_application, method):

    dd = add_days(today(), -1)
    for item in frappe.get_all("Leave Application", filters={"docstatus":1, "to_date":("<", dd)  ,"duty_resumption_date":("=", "")}, fields=["name", "modified", "employee", "to_date", "employee_name"]):
        attendance = frappe.get_doc(dict(doctype='Attendance', employee=item.employee, employee_name=item.employee_name, attendance_date=today(), status="Absent", company=frappe.get_value("Employee", item.employee, "Company")))
        attendance.insert()
        attendance.submit()

    for item in frappe.get_all("Leave Application", filters={"modified": (">=", dd), "docstatus":1, "duty_resumption_date":("!=", "")}, fields=["name", "modified", "employee", "to_date", "employee_name", "duty_resumption_date"]):
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

#10/13
# This function will not allow canceling "Expense Claim" if it is linked to a Salary Slip.
# The "Salary Slip" needs to be cancelled FIRST before allowing this document to be cancelled.
# ********  Expense Claim - On Cancel  ********
def cancel_expense_claim(expense_claim, method):
    if expense_claim.salary_slip:
        #frappe.errprint('Please cancel the associated Salary Slip prior to canceling this document.')
        frappe.throw('Please cancel the associated Salary Slip prior to canceling this document.')

#11/13
# This function cancels "Additional Salary" associated with Submitted "Timesheet"
# ********  Timesheet - On Cancel  ********
def cancel_timesheet(timesheet, method):
    if timesheet.salary_slip:
        frappe.throw('Please cancel the associated Salary Slip prior to canceling this document.')
    else:
        for item in frappe.get_all("Addtional Salary", filters={"timesheet": timesheet.name}, fields=["name"]):
            a_s=frappe.get_doc("Additional Salary", item.name)
            a_s.cancel()

#12/13
# This function checks if there is a 'Salary Payment' linked to this 'Payroll Entry' and throws an error if it exists.
# then it Cancels the Payroll Entry.
# ********  Payroll Entry - On Cancel  ********
def cancel_payroll_entry(payroll_entry, method):
    ss_list = frappe.get_all('Salary Slip', filters={
                    'docstatus': 1,
                    'payroll_entry': payroll_entry.name,
                    'salary_payment': ["!=", ''],
                }, fields=['name'])
    if ss_list:
        frappe.throw('Please cancel the associated Salary Payment first, prior to canceling this document.')
    else:
        frappe.message('Please cancel the Generated Journal Entry from the System.')

#13/13
# ****************************   DISABLED   **********************************************************************
# This function checks if there is a 'Salary Payment' linked to this 'Payroll Entry' and throws an error if it exists.
# then it deletes the Payroll Entry.
# ********  Payroll Entry - On Cancel  ********
def delete_payroll_entry(payroll_entry, method):
    ss_list = frappe.get_all('Salary Slip', filters={
                    'docstatus': 1,
                    'payroll_entry': payroll_entry.name,
                    'salary_payment': ["!=", ''],
                }, fields=['name'])
    if ss_list:
        frappe.throw('Please cancel the associated Salary Payment first, prior to canceling this document.')
    else:
        frappe.message('Please cancel the Generated Journal Entry from the System.')
