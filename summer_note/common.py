from __future__ import unicode_literals
from asyncio.proactor_events import _ProactorBaseWritePipeTransport
from calendar import c
from distutils.log import error
#from socket import SO_VM_SOCKETS_BUFFER_MIN_SIZE
#from ssl import ALERT_DESCRIPTION_BAD_CERTIFICATE_HASH_VALUE
#from tkinter import dnd
#from dbm.dumb import _KeyType
import frappe, requests, urllib3, json, dateutil.parser, urllib, dateutil.relativedelta
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import flt, add_days, date_diff, get_request_site_address, formatdate, getdate, month_diff, today, get_link_to_form, get_url_to_form
from erpnext.hr.doctype.employee.employee import get_holiday_list_for_employee
from erpnext.accounts.utils import get_balance_on
from json import dumps
from datetime import date, timedelta, datetime
from frappe.utils.response import json_handler
from dateutil.relativedelta import relativedelta
from frappe.model.mapper import get_mapped_doc
from erpnext.stock.doctype.item.item import get_item_defaults
from erpnext.stock.doctype.serial_no.serial_no import auto_fetch_serial_number
import xml.etree.ElementTree as ET
import math


#***VERSION 13 ONLY **** LOGGER ADDED 2022-070-12 ***********************
#frappe.utils.logger.set_log_level("DEBUG")
#logger = frappe.logger("NestLog", allow_site=True, file_count=50)
#*********************** LOGGER ADDED 2022-070-12 ***********************

def pull_po_number(purchase_receipt, method):
	items = frappe.get_all("Purchase Receipt Item", filters={"parent": purchase_receipt.name}, fields=["name"])
	if items:
		pri = frappe.get_doc("Purchase Receipt Item", items[0].name)
		po_number = pri.purchase_order
		sql = "UPDATE `tabPurchase Receipt` SET po_number = '" + po_number + "' WHERE name = '" + purchase_receipt.name + "'"
		frappe.db.sql (sql)

# def correct_discount_amount(purchase_receipt, method):
# 	frappe.msgprint('VALIDATE')
# 	if purchase_receipt.discount_amount > 0 and purchase_receipt.additional_discount_percentage == 0:
# 		amount = 0
# 		net_amount = 0
# 		for item in frappe.get_all("Purchase Receipt Item", filters={"parent": purchase_receipt.name}, order_by="idx",fields=["name", "item_code", "amount", "net_amount"]):
# 			amount = amount + item.amount
# 			net_amount = net_amount + item.net_amount
# 		purchase_receipt.discount_amount = amount - net_amount
# 		purchase_receipt.base_discount_amount = purchase_receipt.discount_amount * purchase_receipt.conversion_rate
# 		frappe.msgprint('discount_amount = ' + str(amount - net_amount))

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
	##frappe.errprint (str(ssta))
	sst = frappe.get_doc("Salary Structure", ssta)
	##frappe.errprint (str(sst))
	for item in sst.get("earnings"):
		if item.salary_component == "Basic":
			basic = item.amount
		if item.salary_component == "Op.Basic":
			basic = item.amount    
	##frappe.errprint('# Basic ' + str(basic))
	if emp.ot_entitled:
		##frappe.errprint('# OT Entitled')
		for item in timesheet.get("time_logs"):
			##frappe.errprint (str(item.ot) + ' hours ' + str(item.hours))
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
	##frappe.errprint ('Processing for ' + salary_slip.employee)
	##frappe.errprint ('******** 3 ADD EXPENSE CLAIMS ********')
	if salary_slip.expense_claim_added == 0:
		##frappe.errprint('Adding Expense Claims')
		exp_claim =  frappe.get_all('Expense Claim', filters={
				'status': 'Unpaid',
				'employee': salary_slip.employee,
				'docstatus':1,
			}, fields=['name', 'total_sanctioned_amount'])

		if exp_claim:
			##frappe.errprint('Expense Claims found for Employee ' + salary_slip.employee)
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
			##frappe.errprint('Adding Expense Claim Component to Salary Slip')
			salary_slip.append("earnings",{
						"salary_component":"Expense Claim",
						"amount":claim_total
						})
			salary_slip.expense_claim_added = 1

			#*******************************************************************************************************************************
			# ADDED CODE
			nest_cc = frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center")
			#rappe.errprint('3. add_expense_claim Cost Center - ' + nest_cc)
			#nest_cc = frappe.get_value("Company", salary_slip.company, "cost_center")
			#*******************************************************************************************************************************
			salary_exp_account = frappe.get_value("Company", salary_slip.company, "default_payroll_payable_account")
			exp_account = frappe.get_value("Company", salary_slip.company, "default_expense_claim_payable_account")
			pay_control = frappe.get_value("Company", salary_slip.company, "payroll_controll")

			##frappe.errprint('3. Generating Expense Claim JV')
			jv = frappe.new_doc("Journal Entry")
			jv.company = salary_slip.company
			jv.posting_date = salary_slip.posting_date
			jv.title = str(salary_slip.name) + " Expense Claims: " + str(salary_slip.start_date)
			if salary_slip.company == "National Engineering Services & Trading Co LLC":
				jv.naming_series = "JV/HR/.YY./.####"
			if salary_slip.company == "NEST Employment Services LLC":
				jv.naming_series = "NEE-JV/HR/.YY./.####"
			if salary_slip.company == "Firmo Technical Petroleum Services LLC":
				jv.naming_series = "FIRMO-JV/HR/.YY./.####"        
			jv.voucher_type = "Journal Entry"
			##frappe.errprint('Claim_total = ' + str(claim_total) )
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
	##frappe.errprint ('******** 4 ADD BENIFITS ********')
	has_benifits = False
	emp_file = frappe.get_doc("Employee", salary_slip.employee)
	emp = frappe.get_doc("Employee", salary_slip.employee)
	leave_salary_comp = 0
	leave_salary = 0
	basic_ledger = ""
	basic = 0
	leave_ledger = ""
	airticket_ledger = ""
	eosb_ledger = ""
	PFC = 0
  
	sst = frappe.get_doc("Salary Structure", salary_slip.salary_structure)
	PFC= sst.pension_amount

	#*******************************************************************************************************************************
	# ADDED CODE
	nest_cc = frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center")
	##frappe.errprint('Cost Center for ' + salary_slip.employee + ' is ' + nest_cc)
	
	if ((emp_file.leave_salary) or (emp_file.ticket_entitlement) or (emp.eosb_selection != "EOSB Not Entitled") or (PFC > 0)):
		has_benifits = True
	#*******************************************************************************************************************************
		jv = frappe.new_doc("Journal Entry")
		jv.title = str(salary_slip.name) + " Accruals: " + str(salary_slip.start_date)
		jv.company = salary_slip.company
		jv.posting_date = salary_slip.posting_date
		jv.voucher_type = "Journal Entry"
		if salary_slip.company == "National Engineering Services & Trading Co LLC":
			jv.naming_series = "JV/HR/.YY./.####"
		if salary_slip.company == "NEST Employment Services LLC":
			jv.naming_series = "NEE-JV/HR/.YY./.####"
		if salary_slip.company == "Firmo Technical Petroleum Services LLC":
			jv.naming_series = "FIRMO-JV/HR/.YY./.####"

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
 
	##frappe.errprint('4. add_benefits Cost Center - ' + frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"))

	if emp_file.leave_salary:
		for item in salary_slip.get("earnings"):
			included = frappe.get_value("Salary Component", item.salary_component, "include_in_leave_salary_provision")
			if included:
				leave_salary_comp += item.amount
		leave_salary = leave_salary_comp * float(frappe.get_value("Leave Cycle", emp.leave_cycle, "leave_days")) / float(frappe.get_value("Leave Cycle", emp.leave_cycle, "work_days"))
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
		
		# OLD CALCULATION. REPLACED ON 2022-08-17
		# if working_years < 3:
		# 	multiplier = 1 / 3
		# elif working_years < 5:
		# 	multiplier = 2 / 3
		# else:
		# 	multiplier = 1

		# if working_years < 1:
		# 	eosb = 0
		# else:
		# 	eosb = min(multiplier * (min(5, (date_diff(salary_slip.end_date, emp_file.date_of_joining) / 365)) * basic * (12 / 365) * 21) 
		# 	+ ((max(5, (date_diff(salary_slip.end_date, emp_file.date_of_joining) / 365)) - 5) * basic), 24 * basic)

		if working_years < 1:
			eosb = 0
		else:
			eosb = min((min(5, (date_diff(salary_slip.end_date, emp_file.date_of_joining) / 365)) * basic * (12 / 365) * 21) 
			+ ((max(5, (date_diff(salary_slip.end_date, emp_file.date_of_joining) / 365)) - 5) * basic), 24 * basic)

		old_eosb = get_balance_on(eosb_account, salary_slip.end_date, "Employee", salary_slip.employee)
		old_eosb = abs(float(old_eosb))
		##frappe.errprint(old_eosb)
		##frappe.errprint(eosb)
		post_eosb = eosb - old_eosb

		if frappe.get_value("Employee", salary_slip.employee, "eosb_selection") == "EOSB Entitled":
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
	if has_benifits:
		jv.submit()

	salary_slip.calculate_net_pay()

#5/13
# This method adds a "Additional Salary" document as "Additional Dues" Salary Component into the "SalarySlip" against "LEAVE APPLICATIONs" Taken by the employee.
# It depends on the Annual Leave days taken and selection of flag in the Leave application to include_all_leave_salary_and_airfare_dues_with_next_payment.
# ********  Salary Slip - after_insert  ********
def add_dues(salary_slip, method):
	
	##frappe.errprint ('******** 5 ADD DUES ********')
	##frappe.errprint(salary_slip.employee)
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
	##frappe.errprint(la_list)        

	##frappe.errprint('Leave Applications Start Date: ' + str(salary_slip.start_date)) # ****************************************************************************************
	##frappe.errprint('Leave Applications End Date: ' + str(salary_slip.end_date))  # *******************************************************************************************
	##frappe.errprint('Leave Applications Found: ' + str(len(la_list))) # *******************************************************************************************************

   
	for la_item in la_list:
		#frappe.errprint('Processing Leave Application: ' + str(la_item.name))  # **********************************************************************************************
		leave_application = frappe.get_doc("Leave Application", la_item.name)
		company = frappe.get_value("Employee", leave_application.employee, "company")
		#frappe.errprint('EMPLOYEE COMPANY: ' + company) 
		lc = frappe.get_value("Employee", leave_application.employee, "leave_cycle")
		ld = frappe.get_value("Leave Cycle", lc, "leave_days")
		wd = int(salary_slip.total_working_days)
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
		#frappe.errprint('Include Ticket: ' +str(leave_application.include_all_leave_salary_and_airfare_dues_with_next_payment))
		#frappe.errprint('Leave Type: ' + leave_application.leave_type)
		#if leave_application.include_all_leave_salary_and_airfare_dues_with_next_payment and leave_application.leave_type != "Leave Without Pay" and leave_application.leave_type != "Sick Leave":
		#if str(leave_application.include_all_leave_salary_and_airfare_dues_with_next_payment) == '1' and leave_application.leave_type == "Annual Leave":
		if (leave_application.include_all_leave_salary_and_airfare_dues_with_next_payment or leave_application.include_leave_provisions) and leave_application.leave_type == "Annual Leave":
			#frappe.errprint ('INSIDE LONG LEAVE')
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
				jv.title = str(salary_slip.name) + " Leave Salary: " + str(salary_slip.start_date)
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
						"debit_in_account_currency": -ls,
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
						"credit_in_account_currency": -ls,
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
						"debit_in_account_currency": -ar,
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
						"credit_in_account_currency": -ar,
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
			#frappe.errprint("Full Leave: Adding to Leave Application " + str(leave_application.name) + " a salary_slip " + str(salary_slip.name))
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

				#lscal = min(round((leave_application.total_leave_days / float(ld) * lsal) * 100) / 100, abs(ls))
				lscal = min(round((leave_application.total_leave_days / float(wd) * lsal) * 100) / 100, abs(ls))
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
					#frappe.errprint('Calculated Leave Salary for : ' + leave_application.employee + ' is ' + str(lscal)) 
					#frappe.errprint('Employee Department : ' + frappe.get_value("Employee", leave_application.employee, "department"))
					#frappe.errprint('Employee Cost Center : ' + frappe.get_value("Department", frappe.get_value("Employee", leave_application.employee, "department"), "cost_center"))

					jv = frappe.new_doc("Journal Entry")
					jv.company = company
					jv.posting_date = leave_application.from_date
					jv.title = str(salary_slip.name) + " Leave Salary: " + str(salary_slip.start_date)
					if company == "National Engineering Services & Trading Co LLC":
						jv.naming_series = "JV/HR/.YY./.####"
					if company == "NEST Employment Services LLC":
						jv.naming_series = "NEE-JV/HR/.YY./.####"
					if company == "Firmo Technical Petroleum Services LLC":
						jv.naming_series = "FIRMO-JV/HR/.YY./.####"
					jv.voucher_type = "Journal Entry"
					if (lscal) > 0:
						#frappe.errprint('Appending to JV')
						#frappe.errprint('Debit Ac: ' + str(frappe.get_value("Company", company, "default_leave_salary_payable")))
						#frappe.errprint('Credit Ac: ' + str(ls_account_ledger))
						##frappe.errprint('Appending to JV')
						##frappe.errprint('Appending to JV')
						jv.append("accounts",{
								"account": frappe.get_value("Company", company, "default_leave_salary_payable"),
								"party_type":"Employee",
								"party":leave_application.employee,
								"debit_in_account_currency": lscal,
								"divisions": frappe.get_value("Department", frappe.get_value("Employee", leave_application.employee, "department"), "division"),
								"department":frappe.get_value("Employee", leave_application.employee, "department"),
								"cost_center":frappe.get_value("Department", frappe.get_value("Employee", leave_application.employee, "department"), "cost_center"),
								"employee":leave_application.employee,
								"user_remark":leave_application.name
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
						#frappe.errprint("Short Leave: Adding to Leave Application " + str(leave_application.name) + " a salary_slip " + str(salary_slip.name))
						frappe.set_value("Leave Application", leave_application.name, "salary_slip", salary_slip.name)

	salary_slip.calculate_net_pay()
	salary_slip.save()
	salary_slip.reload()


	#Inter Company
	o_comp = frappe.get_value("Employee", salary_slip.employee, "company")
	o_comp_doc = frappe.get_doc("Company",o_comp )
	s_comp = frappe.get_value("Employee", salary_slip.employee, "sponsoring_company")
	s_comp_ledger = "" 
	salary_payable_ledger = frappe.get_value("Company",salary_slip.company, "default_payroll_payable_account")

	if salary_slip.company != s_comp:
		#frappe.errprint("Inter-Company Transaction for " + str(salary_slip.name))
		jv = frappe.new_doc("Journal Entry")
		jv.title = str(salary_slip.name) + " Inter Company: " + str(salary_slip.start_date)
		jv.company = salary_slip.company
		jv.posting_date = salary_slip.posting_date
		if frappe.get_value("Employee",salary_slip.employee, "company") == "National Engineering Services & Trading Co LLC":
			jv.naming_series = "JV/HR/.YY./.####"
		if frappe.get_value("Employee",salary_slip.employee, "company") == "NEST Employment Services LLC":
			jv.naming_series = "NEE-JV/HR/.YY./.####"
		if frappe.get_value("Employee",salary_slip.employee, "company") == "Firmo Technical Petroleum Services LLC":
			jv.naming_series = "FIRMO-JV/HR/.YY./.####"
		jv.voucher_type = "Journal Entry"

		for item in o_comp_doc.get("related_parties_receivable_account"):
			if item.company == s_comp:
				s_comp_ledger = item.receivable_account

		jv.append("accounts",{
					"account": s_comp_ledger,
					"party_type":"Employee",
					"party":salary_slip.employee,
					"credit_in_account_currency": salary_slip.net_pay,
					"divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
					"department":frappe.get_value("Employee", salary_slip.employee, "department"),
					"cost_center":frappe.get_value("Company", frappe.get_value("Employee",salary_slip.employee, "company"), "cost_center"),
					"employee":salary_slip.employee,
					"user_remark":salary_slip.name
					})
		jv.append("accounts",{
					"account": salary_payable_ledger,
					"party_type":"Employee",
					"party":salary_slip.employee,
					"debit_in_account_currency": salary_slip.net_pay,
					"divisions": frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "division"),
					"department":frappe.get_value("Employee", salary_slip.employee, "department"),
					"cost_center":frappe.get_value("Department", frappe.get_value("Employee", salary_slip.employee, "department"), "cost_center"),
					"employee":salary_slip.employee,
					"user_remark":salary_slip.name
					})
		jv.salary_slip = salary_slip.name
		jv.save()
		jv.submit()

#6/13
# This adds the employees monthly Accrued Leave DAYS entry in the leave days ledger.
# ********  Salary Slip - after_insert  ********
@frappe.whitelist()  # WHY whitelist it?? 
def allocate_leave(salary_slip, method):
	for item in frappe.get_all("Employee", filters={"status": "Active",  "leave_salary": 1, "Employee": salary_slip.employee}, fields=["name"]): # FIXED NOW *********************   ALL EMPLOYEES !!!    *******************
		emp = frappe.get_doc("Employee", item.name)
		mldays = 0
		if emp.leave_cycle:
			#frappe.errprint(emp.name)
			lc = frappe.get_doc("Leave Cycle", emp.leave_cycle)
			#*******************************************************************************************************************************
			# CHANGED 'item' below to 'item1' not to conflict with 'item' in the above loop
			#******************************************************************************************
			d = str(salary_slip.start_date) # datetime.now()
			lc_month = d[5:7] #d.strftime("%m")
			#frappe.errprint (d)
			#frappe.errprint (lc_month)
			for iteml in lc.get("monthly_leave"):
				if int(iteml.month) == int(lc_month):
					mldays = iteml.leaves
			l_days = round((float(salary_slip.payment_days) / float(salary_slip.total_working_days)) * float(mldays) * 2) / 2


			# ********************************  ADDED 2023-03-02  ***************************************
			# CREATE NEW LEAVE ALLOCATION FOR NEW EMPLOYEES IF NO PREVIOUS LEAVE ALLOCATION IS FOUND..
			la_list = frappe.get_all("Leave Ledger Entry", filters={
				"employee": emp.name,  
				"leave_type": "Annual Leave", 
				"transaction_type":"Leave Allocation"
				}, fields=["transaction_name", "from_date", "to_date"], order_by="creation desc")
			if la_list:
				pass
			else:
				la = frappe.new_doc("Leave Allocation")
				la.employee = emp.name
				la.leave_type = "Annual Leave"
				la.from_date = "2021-01-01"
				la.to_date = "2030-12-31"
				la.leave_period = "HR-LPR-2021-00001"
				la.new_leaves_allocated = 0
				la.carry_forward = 0
				la.save()
				la.submit()
			# ********************************  ADDED 2023-03-02  ***************************************

			la_list = frappe.get_all("Leave Ledger Entry", filters={
				"employee": emp.name,  
				"leave_type": "Annual Leave", 
				"transaction_type":"Leave Allocation"
				}, fields=["transaction_name", "from_date", "to_date"], order_by="creation desc")
			if la_list:
				
				ll = frappe.new_doc("Leave Ledger Entry")
				ll.employee = emp.name
				lp = frappe.get_all("Leave Period", filters={"company":salary_slip.company, "is_active":1}, fields=["name", "from_date", "to_date"])
				ll.leave_type = "Annual Leave"
				ll.transaction_type = "Leave Allocation"
				ll.transaction_name = la_list[0].transaction_name
				ll.salary_slip = salary_slip.name
				ll.from_date = lp[0].from_date
				ll.to_date = lp[0].to_date
				ll.leaves = l_days
				ll.save()
				#ll.submit()            SHOULD BE SUBMITTED AT SALARY PAYMENT ONLY,,,,!
			#frappe.errprint("Generated Leave Days for " + emp.name + ' for ' + str(l_days))

#7/13
# This code cancels and Unmarks the "Expense Claim" and "Leave Application" documents if the "SalarySlip" is Cancelled.
# ********  Salary Slip - On Cancel  ********
def cancel_salary_slip(salary_slip, method):
	for item in frappe.get_all("Expense Claim", filters={"salary_slip": salary_slip.name}, fields=["name"]):
		#frappe.errprint('Unmark: Found Expense Claim ' + str(item.name)) #*********************************************************************************************************************
		frappe.set_value("Expense Claim", item.name, "salary_slip", "")
		frappe.set_value("Expense Claim", item.name, "status", "Unpaid")

	for item in frappe.get_all("Leave Application", filters={"salary_slip": salary_slip.name}, fields=["name"]):
		#frappe.errprint('Unmark: Found Leave Application ' + str(item.name)) #*********************************************************************************************************************
		frappe.set_value("Leave Application", item.name, "salary_slip", "")
		for item1 in frappe.get_all("Additional Salary", filters={"leave_application": item.name}, fields=["name"]):
			#frappe.errprint('Delete: Found LA Additional Salaries ' + str(item1.name)) #*********************************************************************************************************************
			a_s=frappe.get_doc("Additional Salary", item1.name)
			a_s.cancel()
			a_s.delete()

	for item in frappe.get_all("Journal Entry", filters={"salary_slip": salary_slip.name}, fields=["name"]):
		#frappe.errprint('Delete: Found JV ' + str(item.name)) #*********************************************************************************************************************
		jv=frappe.get_doc("Journal Entry", item.name)
		jv.cancel()
		jv.delete()

	for item in frappe.get_all("Additional Salary", filters={"salary_slip": salary_slip.name}, fields=["name"]):
		#frappe.errprint('Delete: Found AdditionalSalaries ' + str(item.name)) #*********************************************************************************************************************
		a_s=frappe.get_doc("Additional Salary", item.name)
		a_s.cancel()
		a_s.delete()
	
	for item in frappe.get_all("Leave Ledger Entry", filters={
		"salary_slip": salary_slip.name, 
		'docstatus':0
		}, fields=["name"]):
		#frappe.errprint('Delete: Found Leave Ledger Entries ' + str(item.name)) #*********************************************************************************************************************
		ll=frappe.get_doc("Leave Ledger Entry", item.name)
		#ll.cancel() NOT REQUIRED AT THIS STAGE.  THE ENTRY SHOULD ONLY BE IN DRAFT STATUS.
		ll.delete()

# 8/13
# This adds a Project agaist Every SO except for Engineering Services and Vendor Projects.
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
		##frappe.errprint('Please cancel the associated Salary Slip prior to canceling this document.')
		frappe.throw('Please cancel the associated Salary Slip prior to canceling this document.')

#11/13
# This function cancels "Additional Salary" associated with Submitted "Timesheet"
# ********  Timesheet - On Cancel  ********
def cancel_timesheet(timesheet, method):
	if timesheet.salary_slip:
		frappe.throw('Please cancel the associated Salary Slip prior to canceling this document.')
	else:
		#frappe.errprint ('Cancel TS No SalSlip')
		for item in frappe.get_all('Additional Salary', filters={'timesheet': timesheet.name}, fields=['name']):
			#frappe.errprint ('In loop')
			a_s=frappe.get_doc("Additional Salary", item.name)
			a_s.cancel()

#12/13
# This function checks if there is a 'Salary Payment' linked to this 'Payroll Entry' and throws an error if it exists.
# then it Cancels the Payroll Entry.
# ********  Payroll Entry - On Cancel  ********
def cancel_payroll_entry(payroll_entry, method):
	ss_submitted=False
	#frappe.errprint('CANCELLING PAYROLL ENTRY.')
	sss_list = frappe.get_all('Salary Slip', filters={
					'docstatus': 1,
					'payroll_entry': payroll_entry.name,
					'salary_payment': ["!=", ''],
				}, fields=['name', 'salary_payment'])
	if sss_list:
		sp = frappe.get_doc('Salary Payment', sss_list[0].salary_payment)
		frappe.throw('Salary Payment ' + sp.name + ' is linked to this document.\n Please cancel it prior to canceling this document.')
	else:
		#frappe.errprint('PAYROLL ENTRY NOT LINKED TO SALARY PAYMENT.')
		css_list = frappe.get_all('Salary Slip', filters={
					'docstatus': 1,
					'payroll_entry': payroll_entry.name,
					'salary_payment': '',
			}, fields=['name', 'journal_entry'])
		if css_list:
			jv = frappe.get_value('Salary Slip', css_list[0].name, "journal_entry")     #***************************  added **********************************
			ss_submitted=True
			for item in css_list:
				#frappe.errprint('PAYROLL ENTRY CANCELLING SALARY SLIPS ' + item.name)
				ss = frappe.get_doc("Salary Slip", item.name)
				ss.cancel()
				ss.delete()
			 
		#frappe.errprint('PAYROLL ENTRY CANCELLED SUMBITTED SALARY SLIPS.')
		css_list = frappe.get_all('Salary Slip', filters={
					'docstatus': 0,
					'payroll_entry': payroll_entry.name,
			}, fields=['name'])
		for item in css_list:
			#frappe.errprint('DELETING PAYROLL ENTRY SALARY SLIP ' + item.name)
			ss = frappe.get_doc("Salary Slip", item.name)
			ss.delete()
		#frappe.errprint('PAYROLL ENTRY DELETED SALARY SLIPS.')

		if ss_submitted:
			#frappe.msgprint('Please cancel the Generated Journal Entry from the System.')
			#frappe.errprint('PAYROLL ENTRY DELETING PAYROLL LIABILITY JV.')
			jv_doc=frappe.get_doc("Journal Entry", jv)
			jv_doc.cancel()
			jv_doc.delete()
			#frappe.errprint('PAYROLL ENTRY DELETED PAYROLL LIABILITY JV.')




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
		frappe.msgprint('Please cancel the Generated Journal Entry from the System.')

#14/13
def clear_leave_policy(salary_slip, method):
	emp_list = frappe.get_all('Leave Allocation', filters={}, fields=['name', 'leave_policy'])
	if emp_list:
		for item in emp_list:
			emp = frappe.get_doc('Leave Allocation', item.name)
			#frappe.errprint('Clearing Leave Policy for ' + emp.name)
			if emp.leave_policy:
				emp.leave_policy = ''
				emp.save()
		#frappe.errprint('DONE Clearing Leave Policy')

# 15/13 128.199.107.242
#*******************************************************************************  ADDED 24 - 10 - 2021  ***************************************************************
# NOT USED ANY MORE..
# REPLACED WITH get_projected_leave_days() IN leave_application.py and trigger calls from leave_application.js ***************** 26 - 10 - 2021 ***********************
@frappe.whitelist()
def set_projected_leave_balance(leave_application,method):
	#frappe.errprint('Processing PROJECTED LEAVE BALANCE.')
	employee = frappe.get_doc("Employee", leave_application.employee)
	#frappe.errprint('Employee: ' + employee.name)
	leave_type = leave_application.leave_type
	#frappe.errprint('Leave Type: ' + leave_type)
	
	if (employee and leave_type == "Annual Leave" and leave_application.from_date and leave_application.to_date):
		#frappe.errprint('ALL FIELDS ARE SET.  PROCEEDING......')
		#1 Get Last Entry in Leave Ledger pick up its date:
		la_list = frappe.get_all("Leave Ledger Entry", filters={
					"employee": employee.name,  
					"leave_type": "Annual Leave", 
					"transaction_type":"Leave Allocation"
					}, fields=["transaction_name", "from_date", "to_date", "creation"], order_by="creation desc")
		if la_list:
			last_leave_ledger_entry_date = la_list[0].creation
			#frappe.errprint('last_leave_ledger_entry_date : ' + str(last_leave_ledger_entry_date))
		else:
			last_leave_ledger_entry_date = date.today() - 28 # Last Month
			#frappe.errprint('last_leave_ledger_entry_date NOT FOUND: ' + str(last_leave_ledger_entry_date))
		#2 Get Application Date:
		application_date= date.today()
		#frappe.errprint('application_date :' + str(application_date))

		#3 Get Current Accrued Leave Balance:
		leave_balance = flt(leave_application.leave_balance)    #************************
		#frappe.errprint('leave_balance :' + str(leave_balance))

		#4 Get Leave Start Date:
		from_date = leave_application.from_date
		#frappe.errprint('from_date :' + str(from_date))

		#5 Project Accruals:
		if int(str(application_date)[5:7]) == int(str(last_leave_ledger_entry_date)[5:7]) :
			start_month = int(str(application_date)[5:7]) + 1
			#frappe.errprint('SAME Starting Month :' + str(application_date) + ' ' + str(last_leave_ledger_entry_date)[5:7])
		else:
			start_month = int(str(application_date)[5:7])
			#frappe.errprint('DIFFERENT Starting Month :' + str(application_date) + ' ' + str(last_leave_ledger_entry_date)[5:7])
		
		end_month = int(str(from_date)[5:7])
		#frappe.errprint('End Month :' + str(end_month))
		m=int(start_month)
		projected_accruals=0
		while m < 100:
			#frappe.errprint('Looping from the TOP.')
			lc = frappe.get_doc("Leave Cycle", employee.leave_cycle)
			for iteml in lc.get("monthly_leave"):
				if int(iteml.month) == m:
					#frappe.errprint('Loop Month :' + str(m) + ', Leaves ' + str(iteml.leaves))
					projected_accruals += flt(iteml.leaves)                                             #************************
					m+=1
				if m > 12:
					m = m - 12
					#frappe.errprint('Reset Month')
				if m == end_month :
					m = 100
					#frappe.errprint('REACHED END MONTH')
					break
					
		#frappe.errprint('Loop COMPLETED. projected_accruals ' + str(projected_accruals))
		
		#6 Get From Month:
		from_month = int(str(from_date)[5:7])
		#frappe.errprint('from_month :' + str(from_month))
		
		#7 Get Days to be worked in Leave month:
		leave_month_payment_days = int(str(from_date)[8:10]) - 1
		#frappe.errprint('leave_month_payment_days :' + str(leave_month_payment_days))

		#8 Get days in the leave start month:
		# (date(2012, 3, 1) - date(2012, 2, 1)).days
		days_in_leave_month = int((date(int(str(from_date)[0:4]), int(str(from_date)[5:7]) + 1,1) - date(int(str(from_date)[0:4]), int(str(from_date)[5:7]) ,1)).days)
		#days_in_leave_month = monthrange(from_date[0:4], from_date[5:7])[1]
		#frappe.errprint('days_in_leave_month :' + str(days_in_leave_month))

		#9 Get Leave Start Month Monthly Accrual:
		lc = frappe.get_doc("Leave Cycle", employee.leave_cycle)
		for iteml in lc.get("monthly_leave"):
			if int(iteml.month) == int(from_month):
				monthly_accrual = flt(iteml.leaves)
		#frappe.errprint('monthly_accrual :' + str(monthly_accrual))

		#10	Calculate Leave Start Month Expected Accrual:
		start_month_leave_accrual = round(flt(leave_month_payment_days)/flt(days_in_leave_month)*flt(monthly_accrual)*2)/2     #************************
		#frappe.errprint('start_month_leave_accrual :' + str(start_month_leave_accrual))

		#11 Calculated Total Projected Leave Balance [#3 + #5 + #10]:
		projected_leave_balance = leave_balance + projected_accruals + start_month_leave_accrual
		#frappe.errprint('projected_leave_balance :' + str(projected_leave_balance))

		leave_application.projected_leave_balance = projected_leave_balance                                                #************************

#*******************************************************************************  ADDED 24 - 10 - 2021  ***************************************************************

# **************************** CODE ADDED ON 06 - 11 - 2021  **********************************************
# This function changes the expense account of STOCK ENTRY MATERIAL ISSUE AND MATERIAL RECEIPT Transactions to COGC Expense Account
@frappe.whitelist()
def set_etock_entry_expense_account(stock_entry):
	##frappe.errprint('Setting Stock Expense Account for ' + stock_entry)
	se= frappe.get_doc("Stock Entry", stock_entry) 
	cogc_exp_account = frappe.get_value("Company", se.company, "default_cost_of_goods_consumed_account")
	##frappe.errprint('COGC: ' + str(cogc_exp_account))

	if se.purpose == "Material Issue" or se.purpose == "Material Receipt":
		for item in se.items:
			##frappe.errprint('Stock Entry Detail: ' + str (item.name))
			#frappe.set_value('Stock Entry Detail', item.name, 'expense_account', cogc_exp_account)
			item.expense_account = cogc_exp_account
# **********************************************************************************************************

# *******************************************************************************************************************************
# ************************* DELIVERY NOTE STATE MACHINE - 2022-06-19 ************************************************************
# *******************************************************************************************************************************

@frappe.whitelist()
def get_dn_items(dn):
	dn_o = frappe.get_doc("Delivery Note", dn)
	items = []
	for i in dn_o.items:
		#if i.item_grn_no is None or i.item_grn_no == '':  # Just line Items without a GRN
		if (float(i.qty or 0)-float(i.grn_accepted_qty or 0))>0:  # Just line Items without a GRN
			items.append(
				dict(
				name=i.name,
				cust_idx=i.cust_idx,
				item_code=i.item_code,
				item_name=i.item_name,
				qty=float(i.qty or 0)-float(i.grn_accepted_qty or 0),
				)
			)
	return items

@frappe.whitelist()
def add_grn_no(items, delivery_note, d_grn_no, d_grn_date):
	if len(items)>12: # Empty List len({'Items':[]})==12
		itemsj = json.loads(items).get("items")
		for i in itemsj:
			doi_o = frappe.get_doc("Delivery Note Item", i['name'])
			comma = '' # Concatenate Multiple GRNs
			if len(str(doi_o.item_grn_no or '')) > 0:
				comma = ', '
			doi_o.item_grn_no = str(doi_o.item_grn_no or '') + comma + d_grn_no
#			doi_o.item_grn_date = d_grn_date
			doi_o.item_grn_date = max(str(doi_o.item_grn_date or ''), str(d_grn_date or ''))
			doi_o.grn_accepted_qty = doi_o.grn_accepted_qty + float(i['qty'] or 0)
			doi_o.save()

		dn_o = frappe.get_doc("Delivery Note", delivery_note)
		set_dn_status(dn_o)
		dn_o.save()

	else:
		frappe.msgprint('No Items Selected. No GRN Applied.')

	return []

def cancel_dn_nest_status (delivery_note, method=None):
		sql = "UPDATE `tabDelivery Note` SET nest_status = 'Cancelled' WHERE name = '" + delivery_note.name + "'"
		frappe.db.sql (sql)

def set_dn_status(delivery_note, method=None, complete=0):
	if method == 'on_submit':
		complete=2
	if delivery_note.nest_status != "Completed" or complete != 0:
		update_grn_status(delivery_note)
		settings = get_settings(delivery_note, complete)
		##frappe.errprint(settings)
		actions = map_actions(settings)
		
		# actions is an array of five elements: nest_status, POD, ASN, GRN, Completed
		# where the 2nd to 5th can be either: Alert, Clear, Set, Put, or ''.
		if actions == -1:
			pass
		else:
			if str(actions[0]) == 'To Bill': # Check if Partially Invoiced
				actions[0] = check_partially_invoiced (delivery_note, actions[0])
				##frappe.errprint(actions[0])
			delivery_note.nest_status = str(actions[0]) # 1-nest_status
			##frappe.errprint(delivery_note.nest_status)
			set_action_dates(delivery_note, actions[1], "signed_delivery_note") # 2- POD
			set_action_dates(delivery_note, actions[2], "asn_date") # 3- ASN
			set_action_dates(delivery_note, actions[3], "grn_date") # 4- GRN
			set_action_dates(delivery_note, actions[4], "completed_date") # 5- Completed

def check_partially_invoiced (delivery_note, nest_status):
	# nest_status is coming as 'To Bill'. if ivoice(s) are found, the nest_status will be updated 'Partially Invoiced'.
	# if this DN is FULLY invoiced, the status by default will turn to 'Completed', meaning it is "Fully Invoiced".
	sql = "select ( " + \
			"( " + \
			"select ifnull(sum(sii.qty),0) from `tabSales Invoice Item` sii inner join `tabSales Invoice` si on sii.parent = si.name " + \
			"where si.docstatus = 1 and  si.status not in ('Cancelled', 'Closed', 'Draft') and sii.delivery_note = '"  + delivery_note.name + "' " + \
			") " + \
			"/ " + \
			"(select ifnull(total_qty,0) from `tabDelivery Note` where name = '"  + delivery_note.name + "') " + \
			") as ratio"
	ratio = frappe.db.sql(sql)
	if ratio[0][0] == 0:
		return 'To Bill'
	elif ratio[0][0] < 1:
		return 'Partially Invoiced'
	else:
		return 'Completed'

	# invoice_lines = frappe.get_all("Sales Invoice Item", filters={
	# 	'delivery_note':delivery_note.name,},
	# 	fields=['parent'])

	# invoices = set()
	# partial_found = False

	# for invoice_line in invoice_lines:
	# 	invoices.add(invoice_line.parent)

	# for invoice in invoices:
	# 	si = frappe.get_doc("Sales Invoice", invoice)
	# 	if si.docstatus == 1: #1 is Submitted
	# 		partial_found = True

	# if partial_found:
	# 	nest_status = "Partially Invoiced"
	# return nest_status

def update_grn_status(delivery_note):
	# 1st, Flag the GRN_NO Field with Either 'Partial GRN' or 'Completed GRN' or ''
	require_grn = frappe.db.get_value("Customer", delivery_note.customer, "require_grn")
	max_grn_date = date.fromordinal(1)
	grn_status = ''
	
	if require_grn == True:
		total_items = 0
		accepted_items = 0
		for item in frappe.get_all("Delivery Note Item", filters={"parent": delivery_note.name}, \
			fields=["item_grn_no", "item_grn_date", "grn_accepted_qty", "qty"]):

			total_items = total_items + float(item.qty or 0)
			accepted_items = accepted_items + float(item.grn_accepted_qty or 0)
			if item.item_grn_date is not None:
				if item.item_grn_date > max_grn_date:
					max_grn_date = item.item_grn_date

		if accepted_items == 0:
			grn_status = None
			max_grn_date = None
		else:
			if total_items > accepted_items:
				grn_status = "Partial GRN"
			else:
				grn_status = "Completed GRN"
			
		# update the date on the header with the latest GRN date in the child records.
		delivery_note.grn_no = grn_status
		delivery_note.grn_date = max_grn_date

def get_settings(delivery_note, complete=0):
	pod_attach = 0
	asn_no = 0
	if complete == 1:
		status = 'Completed'
	elif complete == 2:
		status = 'To Bill'
	else:
		status = delivery_note.status
	require_pod = bool(frappe.db.get_value("Customer", delivery_note.customer, "require_pod"))
	require_asn = bool(frappe.db.get_value("Customer", delivery_note.customer, "require_asn"))
	require_grn = bool(frappe.db.get_value("Customer", delivery_note.customer, "require_grn"))
	if delivery_note.pod_attach: pod_attach = True
	if delivery_note.asn_no: asn_no = True
	if delivery_note.grn_no:
		grn_nos = delivery_note.grn_no
	else:
		grn_nos = None
	
	return ([status, require_pod, require_asn, require_grn, pod_attach, asn_no, grn_nos])

def map_actions(settings):
	actions = []

	# (Status, Require POD, Require ASN, Require GRN, POD Attach, ASN No, GRN Nos): [nest_status, POD, ASN, GRN, Completed]
	states = {
		('Draft', '', '', '', '', '', ''): ['Draft', '', '', '', ''], 
		('Closed', '', '', '', '', '', ''): ['Closed', '', '', '', ''], 
		('To Bill', False, False, False, '', '', ''): ['To Bill', '', '', '', ''], 
		('To Bill', True, False, False, False, '', ''): ['Pending POD', 'Clear', '', '', ''], 
		('To Bill', True, False, False, True, '', ''): ['To Bill', 'Alert', '', '', ''], 
		('To Bill', True, True, False, False, False, ''): ['Pending ASN', 'Clear', 'Clear', '', ''], 
		('To Bill', True, True, False, True, False, ''): ['Pending ASN', 'Alert', 'Clear', '', ''], 
		('To Bill', True, True, False, False, True, ''): ['Pending POD', '', 'Set', '', ''], 
		('To Bill', True, True, False, True, True, ''): ['To Bill', 'Alert', 'Set', '', ''], 
		('To Bill', True, True, True, False, False, ''): ['Pending ASN', 'Clear', 'Clear', '', ''], 
		('To Bill', True, True, True, True, False, ''): ['Pending ASN', 'Alert', 'Clear', '', ''], 
		('To Bill', True, True, True, False, True, None): ['Pending POD', '', 'Set', 'Clear', ''], 
		('To Bill', True, True, True, True, True, None): ['Pending GRN', 'Alert', 'Set', 'Clear', ''], 
		('To Bill', True, True, True, True, True, 'Partial GRN'): ['Partial GRN', 'Alert', 'Set', 'Put', ''], 
		('To Bill', True, True, True, True, True, 'Completed GRN'): ['To Bill', 'Alert', 'Set', 'Put', ''], 
		('To Bill', True, False, True, False, '', ''): ['Pending POD', 'Clear', '', '', ''], 
		('To Bill', True, False, True, True, '', None): ['Pending GRN', 'Alert', '', 'Clear', ''], 
		('To Bill', True, False, True, True, '', 'Partial GRN'): ['Partial GRN', 'Alert', '', 'Put', ''], 
		('To Bill', True, False, True, True, '', 'Completed GRN'): ['Pending Ariba Upload', 'Alert', '', 'Put', ''], 
		('Completed', False, False, False, '', '', ''): ['Completed', '', '', '', 'Put'], 
		('Completed', True, False, False, False, '', ''): ['Pending POD', 'Clear', '', '', ''], 
		('Completed', True, False, False, True, '', ''): ['Completed', 'Alert', '', '', 'Put'], 
		('Completed', True, True, False, False, False, ''): ['Pending ASN', 'Clear', 'Clear', '', ''], 
		('Completed', True, True, False, True, False, ''): ['Pending ASN', 'Alert', 'Clear', '', ''], 
		('Completed', True, True, False, False, True, ''): ['Pending POD', '', 'Set', '', ''], 
		('Completed', True, True, False, True, True, ''): ['Completed', 'Alert', 'Set', '', 'Put'], 
		('Completed', True, True, True, False, False, ''): ['Pending ASN', 'Clear', '', '', ''], 
		('Completed', True, True, True, True, False, ''): ['Pending ASN', 'Alert', 'Clear', '', ''], 
		('Completed', True, True, True, False, True, None): ['Pending POD', 'Alert', 'Set', 'Clear', ''], 
		('Completed', True, True, True, True, True, None): ['Pending GRN', 'Alert', 'Set', 'Clear', ''], 
		('Completed', True, True, True, True, True, 'Partial GRN'): ['Partial GRN', 'Alert', 'Set', 'Put', ''], 
		('Completed', True, True, True, True, True, 'Completed GRN'): ['Pending Ariba Upload', 'Alert', 'Set', 'Put', ''], 
		('Completed', True, False, True, False, '', ''): ['Pending POD', 'Clear', '', '', ''], 
		('Completed', True, False, True, True, '', None): ['Pending GRN', 'Alert', '', 'Clear', ''], 
		('Completed', True, False, True, True, '', 'Partial GRN'): ['Partial GRN', 'Alert', '', 'Put', ''], 
		('Completed', True, False, True, True, '', 'Completed GRN'): ['Pending Ariba Upload', 'Alert', '', 'Put', '']
	}	

 # Sample settings: ['To Bill', 1, 1, 1, True, True, None]
	for key in states:
		status, require_pod, require_asn, require_grn, pod_attach, asn_no, grn_nos = key
		values = states[key]
		if (
			(status == settings[0] or status == '') and
			(bool(require_pod) == settings[1] or require_pod == '') and
			(bool(require_asn) == settings[2] or require_asn== '') and
			(bool(require_grn) == settings[3] or require_grn == '') and
			(bool(pod_attach) == settings[4] or pod_attach == '') and
			(bool(asn_no) == settings[5] or asn_no == '') and
			(grn_nos == settings[6] or grn_nos == '')
			):
			actions = values
			break

	if len(actions) > 0:
		return actions
	else:
		frappe.msgprint ('State Mapping Failed! Settings: ' + str(settings))
		return -1

def set_action_dates(delivery_note, action, date_field):
	if action == 'Alert':
		# Pass a message to the Form requesting the user to enter the 'date_field'
		if len(str(frappe.db.get_value("Delivery Note", delivery_note.name, date_field))) == 0:
			frappe.msgprint ("Please don't forget to enter the date for " + date_field, "Date Entry required")
	elif action == 'Clear':
		setattr(delivery_note, date_field, None)
	elif action == 'Set':
		if len(str(frappe.db.get_value("Delivery Note", delivery_note.name, date_field))) == 0:
			setattr(delivery_note, date_field, date.today())
	elif action == 'Put':
		setattr(delivery_note, date_field, date.today())
	else:
		pass

# CHECK IF THE SALES ORDER HAS partial_delivery_and_invoicing_not_allowed FLAG SET. IF SO, STOP SAVING IF DELIVERY IS NOT COMPLETE:
# CALLED FROM THE VALIDATE HOOK.
def confirm_partial_delivery_allowed (delivery_note, method=None):
	dni_so = dict()
	for item in delivery_note.items:
		if item.against_sales_order is not None:
			if item.against_sales_order not in dni_so:
				dni_so[item.against_sales_order] = item.qty
			else:
				dni_so[item.against_sales_order] = dni_so[item.against_sales_order] + item.qty
	
	if dni_so:
		for so in dni_so:
			so_o= frappe.get_doc("Sales Order",  so)
			if so_o.partial_delivery_and_invoicing_not_allowed:
				if dni_so[so] != so_o.total_qty:
					frappe.throw("Sales Order " + str(so) + " does not allow Partial Delivery. Save Cancelled.")

@frappe.whitelist()
def complete_dn(delivery_note):
	dn_o = frappe.get_doc("Delivery Note", delivery_note)
	dn_o.nest_status = "Completed"
	dn_o.completed_date = date.today()
	dn_o.save('Update')
	return delivery_note

# This function will be called from the Sales Invoice AFTER Submit and AFTER Cancel events 
def update_dn_nest_status(sales_invoice, method):
	dn_list = []
	si_o=sales_invoice
	if si_o.docstatus >0: # Submitted or Cancelled
		for item in si_o.get("items"):
			if item.delivery_note not in dn_list and item.delivery_note is not None:
				dn_list.append (item.delivery_note)

		if dn_list:
			for dn in dn_list:
				setcomplete=0
				dn_o = frappe.get_doc("Delivery Note", dn)
				sql = "select ((select sum(sii.qty) from `tabSales Invoice Item` sii inner join `tabSales Invoice` si on sii.parent = si.name" + \
					" where si.status not in ('Cancelled', 'Closed', 'Draft') and sii.delivery_note = '"  + dn_o.name + "')" + \
					"-(select total_qty from `tabDelivery Note` where name = '"  + dn_o.name + "')) as diff"
				diff = frappe.db.sql(sql)
				if diff[0][0] == 0:
					setcomplete = 1
				else:
					setcomplete = 2
				
				frappe.errprint ('si status:' + str(si_o.docstatus) + ' dn status: ' + str(dn_o.status)+ 'diff: ' +str(diff) + ' setcomplete: ' + str(setcomplete))

				set_dn_status(dn_o, complete=setcomplete)
				dn_o.save()

# *******************************************************************************************************************************
# ***************************** END DELIVERY NOTE STATE MACHINE  ****************************************************************
# *******************************************************************************************************************************


def pad_comment_with_timestamp (comment, method):
	if comment.content:
		localtime =  datetime.now() + timedelta(hours=4)
		comment.content = localtime.strftime("%Y-%m-%d %H:%M:%S") + " : " + comment.content 

def expire_bank_guarantees():
	frappe.db.sql ("UPDATE `tabBank Guarantee` SET guarantee_status = 'Expired' WHERE expiry_date < CURRENT_DATE() and guarantee_status <> 'Expired';")

def update_item_groups():
	frappe.db.sql ("update `tabItem` i inner join `tabItem Group` g on i.item_group = g.name set i.division = g.divisions where i.division <> g.divisions and i.disabled=0;")
	frappe.db.sql ("update `tabQuotation Item` t inner join `tabItem` i on t.item_code = i.item_code set t.item_group = i.item_group where t.item_group != i.item_group;")
	frappe.db.sql ("update `tabSales Order Item` t inner join `tabItem` i on t.item_code = i.item_code set t.item_group = i.item_group where t.item_group != i.item_group;")
	frappe.db.sql ("update `tabPurchase Order Item` t inner join `tabItem` i on t.item_code = i.item_code set t.item_group = i.item_group where t.item_group != i.item_group;")
	frappe.db.sql ("update `tabPurchase Receipt Item` t inner join `tabItem` i on t.item_code = i.item_code set t.item_group = i.item_group where t.item_group != i.item_group;")
	frappe.db.sql ("update `tabDelivery Note Item` t inner join `tabItem` i on t.item_code = i.item_code set t.item_group = i.item_group where t.item_group != i.item_group;")
	frappe.db.sql ("update `tabStock Entry Detail` t inner join `tabItem` i on t.item_code = i.item_code set t.item_group = i.item_group where t.item_group != i.item_group;")
	frappe.db.sql ("update `tabSales Invoice Item` t inner join `tabItem` i on t.item_code = i.item_code set t.item_group = i.item_group where t.item_group != i.item_group;")
	frappe.db.sql ("update `tabPurchase Invoice Item` t inner join `tabItem` i on t.item_code = i.item_code set t.item_group = i.item_group where t.item_group != i.item_group;")


# *******************************************************************************************************************************
# ***************************** AUTO RESERVE STOCK  ****************************************************************
# *******************************************************************************************************************************

def auto_reserve_stock(sales_order, method):
	reservable_items_found = False
	sql = """select sum(qty) as available from `tabSales Order Item` where 
			parent = '""" + sales_order.name + """' and actual_qty>0;"""	
	data = frappe.db.sql(sql, as_dict=1)

	if data and data[0]["available"] is not None:
		if data[0]["available"] >0:
			#RESERVABLE QUANTITIES FOUND :)
			reservable_items_found = True

	if reservable_items_found:
		ste = frappe.new_doc("Stock Entry")
		ste.stock_entry_type = "Material Transfer"
		ste.purpose = "Material Transfer"
		ste.naming_series = "STE-MT-.#####"
		ste.company = sales_order.company
		ste.sales_order_no = sales_order.name 

		co=""
		if ste.company == "National Engineering Services & Trading Co LLC":
			co = "NE"
		elif ste.company == "NEST Employment Services LLC":
			co = "NEES"
		elif ste.company == "Firmo Technical Petroleum Services LLC":
			co = "FIR"

		ste.from_warehouse = "Stores - " + co
		ste.to_warehouse = "Reservation Warehouse - " + co
		
		# ADD LINE ITEMS
		for item in frappe.get_all("Sales Order Item", filters={"parent": sales_order.name}, order_by="idx", \
			fields=["name", "item_code", "cust_idx", "idx", "qty", "uom", "conversion_factor", "stock_qty", "actual_qty", "ste_reserved_qty"]):
			if item.actual_qty > 0:
				cogs = "5010101001 - COGS Equipment, spares & accessories - " + co
				cc = "Main - " + co
				
				previous_reservation=0
				for stei in ste.get("items"):
					if stei.item_code == item.item_code:
						previous_reservation = previous_reservation + flt(stei.qty)
				resqty = min(item.actual_qty - previous_reservation, item.qty)
				
				if resqty >0:
					# Here we check if the item is has Serial Numbers. If so, auto-fetch serial numbers and add them to the item record.
					serial_no = ''
					item_o = frappe.get_doc('Item', item.item_code)
					#frappe.errprint('item code ' + str(item.item_code) + ' has serial:' + str(item_o.has_serial_no))
					if item_o.has_serial_no:
						#frappe.errprint('HAS SERIAL NO')
						numbers= auto_fetch_serial_number(resqty, item.item_code, ste.from_warehouse)
						#frappe.errprint(str(numbers))
						resqty = min (resqty, len(numbers))
						#frappe.errprint(str(resqty))
						serial_no = "\n".join(numbers)
						#frappe.errprint(str(serial_no))

					child = frappe._dict({
						"item_code": item.item_code,
						"cust_idx": item.cust_idx, 
						"qty": resqty, 
						"uom": item.uom, 
						"conversion_factor": item.conversion_factor, 
						"stock_qty": item.stock_qty,
						"expense_account": cogs,
						"cost_center": cc,
						"so_detail": item.name,
						"serial_no": serial_no,
						})
					#frappe.errprint(str(child))
					ste.append('items',child)

					sql = "update `tabSales Order Item` " + \
						"set ste_reserved_qty = " + str(resqty) + \
						" where name = '" + str(item.name) + "'"
					frappe.db.sql(sql)
				else:
					sql = "update `tabSales Order Item` " + \
						"set ste_reserved_qty = 0" \
						" where name = '" + str(item.name) + "'"
					frappe.db.sql(sql)
	
		ste.insert(ignore_permissions=True)
		ste.submit()

		frappe.db.set_value('Sales Order', sales_order.name, 'reserve_all_available_stock', 1)
		frappe.db.set_value('Sales Order', sales_order.name, 'reservation_entry', ste.name)
		sales_order.reserve_all_available_stock = 1
		sales_order.reservation_entry = ste.name
		sql = "update `tabSales Order Item` " + \
			"set ste_reserved_qty = 0" \
			" where parent = '" + str(sales_order.name) + "' and actual_qty=0"
		frappe.db.sql(sql)		

		frappe.sendmail(recipients='logistics@nest.ae',
		subject=str(sales_order.name) + " Material Reservation created (" + str(ste.name)+ ")",
		message= "The subject Material Transfer/Reservation has been auto-created and submitted by NEST ERP.")
	
# Called Before Cancelling the Sales Order
rsrv = ''
def cancel_reserved_qty(sales_order, method):
	if sales_order:
		global rsrv
	# 2023-02-24: In here, we need to do the following:
	# 1 - Capture the Reservation Document Name
	# 2 - Delink the STE from the SO
	# 3 - Delink the SO from the STE
	# 4 - Reset the Reserved Qty from all SO line Items.
	# 5 - Cancel the STE Document (from Submitted to Cancelled)
	# 6 - Send Email Message to the logistics team that the reservation Has Been CANCELLED.

	# 1 - Capture the Reservation Document Name
		rsrv = str(sales_order.reservation_entry)	
		#frappe.msgprint ('1 *** ' + rsrv)
	# 2 - Delink the STE from the SO
		sales_order.reserve_all_available_stock = 0
		sales_order.reservation_entry = ""
		#frappe.msgprint ('2 *** ' + rsrv)

	# 3 - Delink the SO from the STE
		sql = "update `tabStock Entry` ste set ste.sales_order_no = null where name = '" + rsrv + "';"
		frappe.db.sql(sql)
		#frappe.msgprint ('3 *** ' + rsrv)

	# 4 - Reset the Reserved Qty from all SO line Items. 
		for item in frappe.get_all("Sales Order Item", filters={"parent": sales_order.name}, order_by="idx", fields=["ste_reserved_qty"]):
			item.ste_reserved_qty=0
		#frappe.msgprint ('4 *** ' + rsrv)

	# 5 - Cancel the STE Document (from Submitted to Cancelled)
		# MOVED AFTER CANCELLING THE SO

	# 6 - Send Email Message to the logistics team that the reservation Has Been CANCELLED.
		if rsrv != 'None' and len(rsrv)>0:
			frappe.sendmail(recipients='logistics@nest.ae',
			subject="Sales Order (" + str(sales_order.name) + ") and Material Reservation (" + rsrv + ") are Cancelled",
			message= "Due to the cancellation of the subject Sales Order, the subject Reservation Material Transfer has been auto-cancelled by NEST ERP.")

def cancel_reservation(sales_order, method):
	# 5 - Cancel the STE Document (from Submitted to Cancelled)
	global rsrv
	#frappe.msgprint('5 a Reservation Entry ' + rsrv)
	if rsrv != 'None' and len(rsrv)>0:
		#frappe.msgprint ('5 b *** ' + str(type(rsrv)))
		ste = frappe.get_doc("Stock Entry", rsrv)
		if ste is not None:
			#frappe.msgprint('Reservation Entry ******* ' + rsrv)
			ste.cancel()

	rsrv=''


# Called if the Sales Order reference is removed from the Stock Entry (custom script Call). 2022-08-14
@frappe.whitelist()
def reset_ste_reserved_qty(stock_entry, sales_order=None):
	# ******  THIS ONLY APPLIES TO STOCK RESERVATION, ie stock_entry_type == 'Material Transfer'
	#frappe.errprint ('SE ' + str(stock_entry))
	#frappe.errprint ('SO ' + str(sales_order))
	se = frappe.get_doc("Stock Entry", stock_entry)

	if (sales_order is None or se.docstatus == 0) and se.stock_entry_type == 'Material Transfer':
		#Clear the Sales Order Reservations
		# 1. capture the list of Sales Orders affected to be used in #2 below.
		sql = "select name from `tabSales Order` where reservation_entry =" + \
			" '" + str(stock_entry) + "' and status not in ('Draft', 'Cancelled', 'Closed', 'Completed');"
		so_list=[]
		data = frappe.db.sql(sql, as_dict=1)	
		#frappe.errprint('DATA : ' + str(data))
		for i in data:
			so_list.append(i['name'])
		#frappe.errprint('SO_LIST : ' + str(so_list))
		
		sql = "update `tabSales Order` so inner join `tabSales Order Item` soi" + \
			" on so.name = soi.parent" + \
			" set soi.ste_reserved_qty = 0" + \
			" where so.reservation_entry = '" + str(stock_entry) + "';"
		frappe.db.sql(sql)
		sql = "update `tabSales Order`" + \
			" set reservation_entry = null" + \
			" where reservation_entry = '" + str(stock_entry) + "';"
		frappe.db.sql(sql)

		# 2. the below loop is intended to run validate, and fill in missing fields in the child tables.
		for so in range(len(so_list)):
			#frappe.errprint(so_list[so])
			so_o=frappe.get_doc("Sales Order", so_list[so])
			so_o.save()

	elif (sales_order is not None and se.docstatus == 1) and se.stock_entry_type == 'Material Transfer': # Stock Entry is SUMBITTED AND there is a Sales Order Linked.
		sql = "update `tabSales Order` so inner join `tabSales Order Item` soi" + \
			" on so.name = soi.parent" + \
			" set soi.ste_reserved_qty = 0" + \
			" where so.reservation_entry = '" + str(stock_entry) + "';"
		frappe.db.sql(sql)
		qty_reserved=False
		#frappe.errprint('*** APPLY RESERVATION ' + str(stock_entry) + ' TO THE ENTERED SALES ORDER *** : ' + str(sales_order))
		# Loop through the ste Items, then loop through the SO which DO NOT have a reserved qty, and set the reservation qty there
		for ste_item in frappe.get_all("Stock Entry Detail", filters={"parent": stock_entry}, order_by="idx", \
			fields=["idx", "item_code", "cust_idx", "qty","so_detail"]):
			for so_item in frappe.get_all("Sales Order Item", filters={"parent": sales_order}, order_by="idx", \
				fields=["name", "item_code", "cust_idx", "qty", "uom", "conversion_factor", "stock_qty", "actual_qty", "reserved_qty"]):
#				if so_item.reserved_qty == 0 and ste_item.item_code == so_item.item_code:
				item =  frappe.get_doc("Sales Order Item", so_item.name)
				if so_item.name == ste_item.so_detail:
					#frappe.errprint ('**** Reserving item ' + str(so_item.name) + ' for qty ' + str(ste_item.qty) )
					item.ste_reserved_qty = ste_item.qty
					item.save()
					qty_reserved=True

		if qty_reserved:
			so_o=frappe.get_doc("Sales Order", sales_order)
			so_o.reservation_entry = stock_entry
			so_o.reserve_all_available_stock = 1
			so_o.save()


# *******************************************************************************************************************************
# ***************************************** CALL-ORDER CREATION  ****************************************************************
# *******************************************************************************************************************************
@frappe.whitelist()
def validate_call_off_order (filename, filepath, blanket_order_no):
	error = 0
	error_message = ''
	filepath = '/home/frappe/frappe-bench/sites/new.nesterp.com' + filepath
	parsed = parse_xml_file(filepath)
	if parsed[0] != 0:
		error = parsed[0]
		error_message = parsed[1]

	else: # File Parsed Correctly... Now perform other validations...
		co_items = parsed[1]
		bo_o = frappe.get_doc("Blanket Order", blanket_order_no)
		
		# Check that Blanket AGREEMENT/CONTRACT has not EXPIRED...
		#frappe.errprint('Blanket Order Date :'+str(bo_o.to_date))
		#frappe.errprint('XML Order Date:' + str(datetime.date(datetime.strptime(co_items[0]['call_off_order_date'], "%Y-%m-%d"))))
		if bo_o.to_date < datetime.date(datetime.strptime(co_items[0]['call_off_order_date'], "%Y-%m-%d")):
			error = 102
			error_message = 'This agreement has EXPIRED. Call-Off Orders Cannot be accepted.,<hr>'
		else:	
			bo_items=[]
			for boi_o in frappe.get_all("Blanket Order Item", filters={"parent": bo_o.name}, order_by="idx", \
				fields=['name', 'parent', 'idx', 'item_code', 'qty', 'rate', 'customer_item_code', \
					'customer_line_no', 'customer_uom', 'customer_lead_time', 'sold_qty']):
				bo_item = {
					'name' : boi_o.name,
					'parent' : boi_o.parent,
					'idx' : boi_o.idx,
					'item_code' : boi_o.item_code,
					'qty' : boi_o.qty,
					'rate' : boi_o.rate,
					'customer_item_code' : boi_o.customer_item_code,
					'customer_line_no' : boi_o.customer_line_no,
					'customer_uom' : boi_o.customer_uom,
					'customer_lead_time' : boi_o.customer_lead_time,
					'sold_qty' : boi_o.sold_qty,
				}
				bo_items.append(bo_item)

			# 1. Check Call off belongs to this contract...
			if bo_o.customer_order != co_items[0]['customer_contract']:
				error = 103
				error_message = 'File belongs to Contract or Agreement no. ' + str(co_items[0]['customer_contract']) + '. Not this agreement.,<hr>'
			else:
				# Loop through items and check:
				for co_item in co_items:
					bo_item_dict=list(filter(lambda bo_item: bo_item['customer_item_code'] == co_item['customer_item_number'], bo_items))

					# 1- Item is in contract/agreement
					if len(bo_item_dict) == 0:
						error = max(104, error)
						error_message = error_message + 'Item ' + str(co_item['customer_item_number']) + ' (line ' + str(co_item['customer_line_no']) + ')' + ' is not in the Agreement.,<hr>'
					else:
						# 2- Rate is the same
						if co_item['rate'] != bo_item_dict[0]['rate']:
							error = max(105, error)
							error_message = error_message + 'Item ' + str(co_item['customer_item_number']) + ' (line ' + str(co_item['customer_line_no']) + ')' + ' has a different rate than the Agreement(line ' + str(bo_item_dict[0]['customer_line_no']) + ').,<hr>'
						# 3- UOM is the same
						if co_item['uom'] != bo_item_dict[0]['customer_uom']:
							error = max(106, error)
							error_message = error_message + 'Item ' + str(co_item['customer_item_number']) + ' (line ' + str(co_item['customer_line_no']) + ')' + ' has a different UOM than the Agreement(line ' + str(bo_item_dict[0]['customer_line_no']) + ').,<hr>'
						# 4- Lead time is equal or more than agreed
						co_leadtime = float((datetime.strptime(co_item['required_date'], "%Y-%m-%d") - datetime.strptime(co_item['call_off_order_date'], "%Y-%m-%d")).days)
						if co_leadtime < float(bo_item_dict[0]['customer_lead_time']):
							error = max(107, error)
							error_message = error_message + 'Item ' + str(co_item['customer_item_number']) + ' (line ' + str(co_item['customer_line_no']) + ')' + ' leadtime is less than the Agreement(line ' + str(bo_item_dict[0]['customer_line_no']) + ').,<hr>'
						# 5- Quantity will not exceed agreed qty - Warning
						if float(bo_item_dict[0]['qty']) < \
							(float(bo_item_dict[0]['sold_qty']) + float(co_item['qty'])):
							error = max(5, error)
							error_message = error_message + 'Warning: Item ' + str(co_item['customer_item_number']) + ' (line ' + str(co_item['customer_line_no']) + ')' + ' sold quantity will exceed the Agreement(line ' + str(bo_item_dict[0]['customer_line_no']) + ').,<hr>'

	if len(error_message)>0:
		error_message = error_message[:-5] # remove the last ',<hr>'

	return ({
		"error":error,
		"message": error_message
	})

def parse_xml_file(filepath):
	try:
		xml_file = ET.parse (filepath)
	except Exception as ex:
		if type(ex).__name__ == 'ParseError':
			return ([101, '**Error: Invalid File Format., '])
		else:
			template = "**Error: {0} occurred:\n{1!r}., "
			message = template.format(type(ex).__name__, ex.args)
			return ([102, message])
	else:
		items=[]
		# Dictionary Should Contain:
		# call_off_order_date, call_off_order_number, call_off_order_value, call_off_order_currency, customer_line_no, 
		# qty, required_date, customer_item_number, rate, item_currency, uom, customer_contract
		root= xml_file.getroot()
		# EXTRACT ORDER HEADER....
		order_header = root.find('Request').find('OrderRequest').find('OrderRequestHeader')
		call_off_order_date = order_header.attrib['orderDate'][0:10]
		call_off_order_number = order_header.attrib['orderID']
		call_off_order_value = float(order_header.find('Total').find('Money').text)
		call_off_order_currency = order_header.find('Total').find('Money').attrib['currency']
		# EXTRACT ORDER LINE ITEMS....
		for line_item in root.find('Request').find('OrderRequest').findall('ItemOut'):
			customer_line_no=line_item.attrib['lineNumber']
			qty=line_item.attrib['quantity']
			required_date=line_item.attrib['requestedDeliveryDate'][0:10]
			customer_item_number=line_item.find('ItemID').find('BuyerPartID').text.lstrip("0")
			rate=float(line_item.find('ItemDetail').find('UnitPrice').find('Money').text)
			item_currency=line_item.find('ItemDetail').find('UnitPrice').find('Money').attrib['currency']
			uom=line_item.find('ItemDetail').find('UnitOfMeasure').text
			customer_contract=line_item.find('MasterAgreementIDInfo').attrib['agreementID']
			item = {
				'call_off_order_date':call_off_order_date,
				'call_off_order_number':call_off_order_number,
				'call_off_order_value':call_off_order_value,
				'call_off_order_currency':call_off_order_currency,
				'customer_line_no':customer_line_no,
				'qty':qty,
				'required_date':required_date,
				'customer_item_number':customer_item_number,
				'rate':rate,
				'item_currency':item_currency,
				'uom':uom,
				'customer_contract':customer_contract
				}
			items.append(item)
		return ([0,items])


@frappe.whitelist()
def create_call_off_order(filepath, blanket_order_no):
	filepath = '/home/frappe/frappe-bench/sites/new.nesterp.com' + filepath

	parsed = parse_xml_file(filepath)
	co_items=parsed[1]
	bo_o = frappe.get_doc('Blanket Order', blanket_order_no)
	bo_items=[]
	for boi_o in frappe.get_all("Blanket Order Item", filters={"parent": bo_o.name}, order_by="idx", \
		fields=['name', 'parent', 'idx', 'item_code', 'qty', 'rate', 'uom', 'customer_item_code', \
			'customer_line_no', 'customer_uom', 'customer_lead_time', 'sold_qty']):
		bo_item = {
			'name' : boi_o.name,
			'parent' : boi_o.parent,
			'idx' : boi_o.idx,
			'item_code' : boi_o.item_code,
			'qty' : boi_o.qty,
			'uom': boi_o.uom,
			'rate' : boi_o.rate,
			'customer_item_code' : boi_o.customer_item_code,
			'customer_line_no' : boi_o.customer_line_no,
			'customer_uom' : boi_o.customer_uom,
			'customer_lead_time' : boi_o.customer_lead_time
		}
		bo_items.append(bo_item)

	so_o = frappe.new_doc('Sales Order')
	so_o.customer = bo_o.customer
	so_o.source = 'Direct from Customer'
	so_o.brand_reference = bo_o.brand_reference
	so_o.company = bo_o.company
	so_o.transaction_date = co_items[0]['call_off_order_date'] #*********OVERWRITTEN FOR TESTING***************************** #date.today()
	so_o.delivery_date = min(co_items, key=lambda x:x['required_date'])['call_off_order_date']
	so_o.po_no = str(co_items[0]['customer_contract']) + ' COO# ' + str(co_items[0]['call_off_order_number']) 
	so_o.po_date = co_items[0]['call_off_order_date']
	so_o.project_type = bo_o.agreement_type
	so_o.currency = co_items[0]['call_off_order_currency']
	so_o.partial_delivery_and_invoicing_not_allowed = bo_o.partial_delivery_and_invoicing_not_allowed
	so_o.icv_retention = bo_o.icv_retention
	so_o.ld_applicable = bo_o.ld_applicable
	so_o.sales_region = bo_o.sales_region

	#frappe.errprint('SO Transaction Date: ' + str(so_o.transaction_date))
	#frappe.errprint('SO Delivery Date: ' + str(so_o.delivery_date))
	#frappe.errprint('CO Date: ' + str(so_o.po_date))

	for co_item in co_items:
		bo_item_dict=list(filter(lambda bo_item: bo_item['customer_item_code'] == co_item['customer_item_number'], bo_items))

		#frappe.errprint('Blanket Order Line #: ' + str(bo_item_dict[0]['idx']))
		#frappe.errprint(', Cust Line #: ' + str(bo_item_dict[0]['customer_line_no']))
		#frappe.errprint(', Customer Item Code: ' + str(co_item['customer_item_number']))
		#frappe.errprint('delivery Date: ' + str(co_item['required_date']))

		additional_notes ='Blanket Order Line #: ' + str(bo_item_dict[0]['idx']) + \
				', Cust Line #: ' + str(bo_item_dict[0]['customer_line_no']) + \
				', Customer Item Code: ' + str(co_item['customer_item_number'])
		item = {
			# Add dictionary of all child fields ...... with reference to the Blanket order Line#
			"cust_idx" :co_item['customer_line_no'],
			"item_code": bo_item_dict[0]['item_code'],
			"qty":co_item['qty'],
			"rate":co_item['rate'],
			"uom": bo_item_dict[0]['uom'],
			"delivery_date": co_item['required_date'],
			"additional_notes": additional_notes,  
			"blanket_order":blanket_order_no,
			"bo_detail": bo_item_dict[0]['name']
		}
		so_o.append("items", item)
	
	#frappe.errprint(str(so_o))

	so_o.insert()
	frappe.db.commit()
	
	return (get_link_to_form("Sales Order", so_o.name))


@frappe.whitelist()
def update_blanket_order_stats(blanket_order_no):
	sql = "update `tabBlanket Order Item` b1 inner join " + \
		"(select boi.name, sum(soi.qty) as Total_Sold, sum(poi.qty) as Total_Ordered from  `tabBlanket Order Item` boi " + \
		"left join `tabPurchase Order Item` poi on boi.name = poi.bo_detail " + \
		"left join `tabSales Order Item` soi on boi.name = soi.bo_detail " + \
		"where boi.parent = '" + blanket_order_no + "' " + \
		"group by boi.name) b2 on b1.name = b2.name " + \
		"set b1.sold_qty= ifnull(b2.Total_Sold,0), b1.ordered_qty = ifnull(b2.Total_Ordered,0);"

	#frappe.errprint ('Updating Child Item Qtys')
	#frappe.errprint (sql)
	frappe.db.sql (sql)

	# Update Blanket Order Header Qtys
	sql = "update `tabBlanket Order` bo  " + \
		"inner join  " + \
			"(select parent,  " + \
			"sum(qty) as total_qty,  " + \
			"sum(qty * rate) as selling_total, " + \
			"sum(qty * buying_rate) as buying_total, " + \
			"sum(sold_qty) as sold_qty, " + \
			"sum(ordered_qty) as bought_qty, " + \
			"sum(sold_qty * rate) as sold_total, " + \
			"sum(ordered_qty * buying_rate) as bought_total " + \
			"from `tabBlanket Order Item` " + \
			"where parent = '" + blanket_order_no + "' " + \
			"GROUP BY parent " + \
			") boi on bo.name = boi.parent " + \
		"set " + \
			"bo.total_qty = boi.total_qty,  " + \
			"bo.selling_total = boi.selling_total, " + \
			"bo.base_selling_total = boi.selling_total * bo.selling_conversion_rate, " + \
			"bo.buying_total = boi.buying_total, " + \
			"bo.base_buying_total = boi.buying_total * bo.buying_conversion_rate, " + \
			"bo.sold_qty = boi.sold_qty, " + \
			"bo.bought_qty = boi.bought_qty, " + \
			"bo.sold_total = boi.sold_total, " + \
			"bo.base_sold_total = boi.sold_total * bo.selling_conversion_rate, " + \
			"bo.bought_total = boi.bought_total, " + \
			"bo.base_bought_total = boi.bought_total * bo.buying_conversion_rate;"

	#frappe.errprint('Updating Header')
	#frappe.errprint (sql)
	frappe.db.sql (sql)

	frappe.db.commit()

@frappe.whitelist()
def get_pending_call_off_order(*args, **kwargs):
	# args =	('Sales Order', '', 'name', 0, '21', {'blanket_order_no': 'COC22/001'})
	# kwargs = {'as_dict': '1'}
	#frappe.errprint(args)
	bo=args[5]['blanket_order_no']
	sql="select so.name as name, so.company as company, so.transaction_date as transaction_date " + \
		"from `tabSales Order` so inner join `tabSales Order Item` soi on so.name = soi.parent " + \
		"left join `tabPurchase Order Item` poi on soi.name = poi.sales_order_item " + \
		"where soi.blanket_order ='" + str(bo) + "' " + \
		"and so.docstatus = 1 and so.status NOT IN ('Draft', 'Cancelled', 'Closed', 'Completed') " + \
		"and poi.sales_order_item is null and (soi.qty-soi.ste_reserved_qty)>0 " + \
		"group by so.name, so.company, so.transaction_date"
	#frappe.errprint (sql)
	return frappe.db.sql(sql, as_dict=1)

@frappe.whitelist()
def create_call_off_purchase_order(blanket_order_no, sales_order_no):
	bo_o = frappe.get_doc('Blanket Order', blanket_order_no)
	so_o = frappe.get_doc('Sales Order', sales_order_no)
	po_o = frappe.new_doc('Purchase Order')
	if bo_o.company == "National Engineering Services & Trading Co LLC":
		co = "NE"
	elif bo_o.company == "NEST Employment Services LLC":
		co = "NEES"
	elif bo_o.company == "Firmo Technical Petroleum Services LLC":
		co = "FIR"

	# Build Blanket Order rates dictionary
	bo_items=[]
	for boi_o in frappe.get_all("Blanket Order Item", filters={"parent": bo_o.name}, order_by="idx", \
		fields=['item_code', 'buying_rate', 'uom', 'buying_lead_time']):
		bo_item = {
			'item_code': boi_o.item_code,
			'buying_rate': boi_o.buying_rate,
			'uom': boi_o.uom,
			'buying_lead_time': boi_o.buying_lead_time
		}
		bo_items.append(bo_item)

	#frappe.errprint('Adding Header fields')
	# ADD PO HEADER ELEMENTS
	po_o.supplier = bo_o.supplier
	po_o.company = bo_o.company
	po_o.transaction_date = so_o.transaction_date #*********OVERWRITTEN FOR TESTING***************************** # date.today()
	po_o.sales_order_no = so_o.name
	po_o.customer = bo_o.customer
	po_o.currency = bo_o.buying_currency
	po_o.set_warehouse = "Stores - " + co	
	po_o.tc_name = bo_o.btc_name
	po_o.payment_terms_template = bo_o.payment_terms_template

	#ADD CHILD ITEMS
	for item in frappe.get_all("Sales Order Item", filters={"parent": so_o.name}, order_by="idx", \
		fields=["name", "item_code", "cust_idx", "idx", "qty", "uom", "conversion_factor", "stock_qty", "actual_qty","ste_reserved_qty", "bo_detail"]):

		min_lead_time = 10000 #Initialize Arbirary Lead Time
		bo_item_dict=list(filter(lambda bo_item: bo_item['item_code'] == item['item_code'], bo_items))
		min_lead_time = min(min_lead_time, int(bo_item_dict[0]['buying_lead_time']))

		cogs = "5010101001 - COGS Equipment, spares & accessories - " + co
		cc = "Main - " + co

		if (item.qty - item.ste_reserved_qty)>0:
			child = frappe._dict({
				"item_code": item.item_code,
				"cust_idx": item.cust_idx, 
				"qty": item.qty - item.ste_reserved_qty, 
				"uom": item.uom, 
				"conversion_factor": item.conversion_factor, 
				"stock_qty": item.stock_qty,
				"schedule_date": po_o.transaction_date + timedelta(days = int(bo_item_dict[0]['buying_lead_time'])),
				"expense_account": cogs,
				"cost_center": cc,
				"sales_order": so_o.name,
				"sales_order_item": item.name,
				"blanket_order": bo_o.name,
				"blanket_order_rate": list(filter(lambda bo_item: bo_item['item_code'] == item.item_code, bo_items))[0]['buying_rate'],
				"bo_detail": item.bo_detail,
				"rate": list(filter(lambda bo_item: bo_item['item_code'] == item.item_code, bo_items))[0]['buying_rate']
				})
			po_o.append('items',child)

	po_o.schedule_date = po_o.transaction_date + timedelta(days = int(min_lead_time))

	po_o.insert()
	frappe.db.commit()

	return (get_link_to_form("Purchase Order", po_o.name))


@frappe.whitelist()
def validate_create_call_off_order (values):
	error=0
	error_message = ""
	values = json.loads(values) # convert the string passed from JS to a dictionary

	co_name = ""
	co_date =""
	co_lines = ""
	if "co_name" in values:
		co_name= values['co_name']
	if "co_date" in values:
		co_date= values['co_date']
	if "co_lines" in values:
		co_lines = values['co_lines']

	# Verify CO Number is entered
	if len(co_name)==0:
		error = 1
		error_message = error_message + "Please enter the Call-Off Number.,<hr>"
	
	# Verify CO Date is entered
	if len(co_date) == 0:
		error = 2
		error_message = error_message + "Please enter the Call-Off Date.,<hr>"

	# Verify CO Lines are entered and Correct
	if len(co_lines) == 0:
		error = 3
		error_message = error_message + "Please enter the Call-Off Line details.,<hr>"
	else:
		# Validate that the lines are entered correctly..
		lines = dict((a.strip(), int(b.strip()))  
                     for a, b in (element.split(':')  
                                  for element in co_lines.split(','))) 

	if len(error_message)>0:
		error_message = error_message[:-5] # remove the last ',<hr>'

	return ({
		"error":error,
		"message": error_message
	})


@frappe.whitelist()
def make_create_call_off_order(values,blanket_order_no):
	values = json.loads(values) # convert the string passed from JS to a dictionary
	co_name = values["co_name"]
	co_date = datetime.strptime(values["co_date"], "%Y-%m-%d")

	co_lines = values["co_lines"]
	lines = dict((a.strip(), int(b.strip()))  
					for a, b in (element.split(':')  
								for element in co_lines.split(',')))

	bo_o = frappe.get_doc('Blanket Order', blanket_order_no)
	bo_items=[]
	for boi_o in frappe.get_all("Blanket Order Item", filters={"parent": bo_o.name}, order_by="idx", \
		fields=['name', 'parent', 'idx', 'item_code', 'qty', 'rate', 'uom', 'customer_item_code', \
			'customer_line_no', 'customer_uom', 'customer_lead_time', 'sold_qty']):
		bo_item = {
			'name' : boi_o.name,
			'parent' : boi_o.parent,
			'idx' : boi_o.idx,
			'item_code' : boi_o.item_code,
			'qty' : boi_o.qty,
			'uom': boi_o.uom,
			'rate' : boi_o.rate,
			'customer_item_code' : boi_o.customer_item_code,
			'customer_line_no' : boi_o.customer_line_no,
			'customer_uom' : boi_o.customer_uom,
			'customer_lead_time' : boi_o.customer_lead_time
		}
		bo_items.append(bo_item)

	so_o = frappe.new_doc('Sales Order')
	so_o.customer = bo_o.customer
	so_o.source = 'Direct from Customer'
	so_o.brand_reference = bo_o.brand_reference
	so_o.company = bo_o.company
	so_o.transaction_date = co_date
	so_o.delivery_date = co_date + timedelta(days=int(bo_items[0]['customer_lead_time']))
	so_o.po_no = co_name
	so_o.po_date = co_date
	so_o.project_type = bo_o.agreement_type
	so_o.currency = frappe.get_value('Blanket Order', blanket_order_no, 'selling_currency')
	so_o.partial_delivery_and_invoicing_not_allowed = bo_o.partial_delivery_and_invoicing_not_allowed
	so_o.icv_retention = bo_o.icv_retention
	so_o.ld_applicable = bo_o.ld_applicable
	so_o.sales_region = bo_o.sales_region

	idx = 0
	for co_item in lines:
		idx=idx +1
		bo_item_dict=list(filter(lambda bo_item: str(int(bo_item['customer_line_no'])) == str(int(co_item)), bo_items))

		additional_notes ='Blanket Order Line #: ' + str(bo_item_dict[0]['idx']) + \
				', Cust Line #: ' + str(bo_item_dict[0]['customer_line_no']) + \
				', Customer Item Code: ' + str(bo_item_dict[0]['customer_item_code'])

		item = {
			# Add dictionary of all child fields ...... with reference to the Blanket order Line#
			"cust_idx" :idx,
			"item_code": bo_item_dict[0]['item_code'],
			"qty":lines[co_item],
			"rate":bo_item_dict[0]['rate'],
			"uom": bo_item_dict[0]['uom'],
			"delivery_date": co_date + timedelta(days=int(bo_item_dict[0]['customer_lead_time'])),
			"additional_notes": additional_notes,  
			"blanket_order":blanket_order_no,
			"bo_detail": bo_item_dict[0]['name']
		}
		so_o.append("items", item)
	
	so_o.insert()
	frappe.db.commit()
	
	return (get_link_to_form("Sales Order", so_o.name))

#*******************************  CHANGED 2023-03-23 *****CALLED FROM QUOTATION CUSTOM SCRIPT **************************************************
@frappe.whitelist()
def last_sales_order_rate(customer, item_code):
    #res = frappe.db.sql("""select rate, currency from `tabSales Order Item` sitems join  `tabSales Order` so on sitems.parent = so.name  where so.customer=%s and sitems.item_code=%s""",(customer, item_code), as_dict=1)
    #*******************************  CHANGED 2023-03-06 *************************************************************
    res = frappe.db.sql ("""select soi.rate, so.currency from `tabSales Order Item` soi join `tabSales Order` so on soi.parent = so.name where so.customer=%s and soi.item_code=%s order by so.transaction_date desc, so.customer, soi.item_code limit 1;""",(customer, item_code), as_dict=1)
    #*******************************  CHANGED 2023-03-06 *************************************************************
    return res

@frappe.whitelist()
def last_purchase_order_rate(item_code):
    #res = frappe.db.sql("""select rate, currency from `tabSales Order Item` sitems join  `tabSales Order` so on sitems.parent = so.name  where so.customer=%s and sitems.item_code=%s""",(customer, item_code), as_dict=1)
    #*******************************  CHANGED 2023-03-06 *************************************************************
    res = frappe.db.sql ("""select poi.rate, po.currency from `tabPurchase Order Item` poi join `tabPurchase Order` po on poi.parent = po.name where poi.item_code=%s order by po.transaction_date desc limit 1;""",(item_code), as_dict=1)
    #*******************************  CHANGED 2023-03-06 *************************************************************
    return res
#*******************************  CHANGED 2023-03-23 *****CALLED FROM QUOTATION CUSTOM SCRIPT **************************************************

@frappe.whitelist()
def get_sales_team(brand, type, region):
	sql = f"""select b.sales_person, b.employee, b.employee_name, b.allocated_percentage 
		from `tabBrand wise Sales Team Contribution` a 
		inner join `tabEmployee Sales Contribution` b 
		on a.name = b.parent
		where a.brand = '{brand}' 
		and a.type = '{type}'
		and a.region = '{region}'
		order by b.idx;"""
	sales_team = frappe.db.sql(sql, as_dict=True)
	return sales_team


#*********************************** ADDED 2023-04-08 CREATE STOCK AGING TABLE FOR STOCK AGING REPORT ***********************
@frappe.whitelist()
def create_stock_aging():
	#frappe.errprint ('**************** Entering create_stock_aging ****************************')

	#1 Delete All Temporary Table, if any.
	sql = """DROP TEMPORARY TABLE IF EXISTS closing_balance;"""
	frappe.db.sql(sql)
	sql = """DROP TEMPORARY TABLE IF EXISTS Positive_Inventory_Transactions;"""
	frappe.db.sql(sql)
	sql = """DROP TEMPORARY TABLE IF EXISTS Aging_Inventory_Transactions;"""
	frappe.db.sql(sql)
	sql = """DROP TABLE IF EXISTS stock_aging;"""
	frappe.db.sql(sql)

	#2 Get Items Closing Balances
	sql = """CREATE TEMPORARY TABLE closing_balance (
			SELECT a.item_code, a.warehouse, b.company, b.Qty_after_transaction as closing_balance, b.valuation_rate from
			(SELECT item_code, warehouse, company, max(creation) as closing_date from `tabStock Ledger Entry` GROUP BY item_code, warehouse) a 
			INNER JOIN 
			(SELECT item_code, warehouse, company, creation, Qty_after_transaction, valuation_rate from `tabStock Ledger Entry`) b
			ON a.item_code = b.item_code and a.warehouse = b.warehouse and a.closing_date = b.creation and a.company = b.company
			INNER JOIN `tabItem` i on a.item_code = i.item_code 
			INNER JOIN `tabWarehouse` w on a.warehouse = w.name
			WHERE i.disabled = 0 and w.disabled = 0 and b.Qty_after_transaction > 0 
			# and b.warehouse = 'Store A'
			# and b.item_code = 'Item A'
			# and b.item_group = 'Spares - Bently Nevada - Principals - Goods'
			ORDER BY a.item_code, a.warehouse
			);
		"""
	frappe.db.sql(sql)

	#3 Filter only Receipts or Additions to Stock
	sql = """CREATE TEMPORARY TABLE Positive_Inventory_Transactions (
			SELECT p.item_code, i.item_name, i.item_group, i.brand, p.warehouse, p.company, p.posting_date, 
			if(p.actual_qty<>0, p.actual_qty, p.qty_after_transaction) as actual_qty, 
			if(p.incoming_rate<>0, p.incoming_rate, cb.valuation_rate) as incoming_rate , cb.closing_balance, 
			datediff(curdate(), p.posting_date)+1 as aged_days, 0 as prev_aged_Qty, 0 as aged_Qty
			FROM `tabStock Ledger Entry` p
			INNER JOIN closing_balance cb
			ON p.item_code = cb.item_code and p.warehouse=cb.warehouse and p.company = cb.company
			INNER JOIN `tabItem` i on p.item_code = i.item_code
			WHERE if(p.actual_qty<>0, p.actual_qty, p.qty_after_transaction) >=0
			);
		"""
	frappe.db.sql(sql)

	#4 Create Index for the Positive_Inventory_Transactions
	sql = """create index idx1 on Positive_Inventory_Transactions (item_code, warehouse);"""
	frappe.db.sql(sql)
	sql = """create index idx2 on Positive_Inventory_Transactions (item_code, warehouse, company);"""
	frappe.db.sql(sql)

	#5 Create the Aging Transactions Table
	sql = """CREATE TEMPORARY TABLE Aging_Inventory_Transactions (
			select a.item_code, a.item_name, a.item_group, a.brand, a.warehouse, a.company, a.posting_date, a.closing_balance, sum(a.actual_qty) as actual_qty, a.aged_days
			, avg(a.incoming_rate) as incoming_rate
			#, sum(a.actual_qty*a.incoming_rate)/sum(a.actual_qty) as incoming_rate
			, case when a.aged_days <= 30 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0)) else 0 end as `0-30`
			, case when a.aged_days <= 30 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0))*avg(a.incoming_rate) else 0 end as `0-30 Value`
			, case when a.aged_days > 30 and a.aged_days <= 90 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0)) else 0 end as `>30`
			, case when a.aged_days > 30 and a.aged_days <= 90 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0))*avg(a.incoming_rate) else 0 end as `>30 Value`
			, case when a.aged_days > 90 and a.aged_days <= 180 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0)) else 0 end as `>90`
			, case when a.aged_days > 90 and a.aged_days <= 180 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0))*avg(a.incoming_rate) else 0 end as `>90 Value`
			, case when a.aged_days > 180 and a.aged_days <= 365 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0)) else 0 end as `>180`
			, case when a.aged_days > 180 and a.aged_days <= 365 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0))*avg(a.incoming_rate) else 0 end as `>180 Value`
			, case when a.aged_days > 365 and a.aged_days <= 730 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0)) else 0 end as `>365`
			, case when a.aged_days > 365 and a.aged_days <= 730 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0))*avg(a.incoming_rate) else 0 end as `>365 Value`
			, case when a.aged_days > 730 and a.aged_days <= 1095 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0)) else 0 end as `>730`
			, case when a.aged_days > 730 and a.aged_days <= 1095 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0))*avg(a.incoming_rate) else 0 end as `>730 Value`
			, case when a.aged_days > 1095 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0)) else 0 end as `>1095`
			, case when a.aged_days > 1095 then least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0))*avg(a.incoming_rate) else 0 end as `>1095 Value`
			from Positive_Inventory_Transactions a left join Positive_Inventory_Transactions b
			on a.item_code = b.item_code and a.warehouse = b.warehouse and a.posting_date < b.posting_date
			group by a.item_code, a.warehouse, a.company, a.posting_date, a.closing_balance #,a.actual_qty
			having least(sum(a.actual_qty), a.closing_balance-ifnull(sum(b.actual_qty),0)) >=0
			order by a.item_code asc, a.warehouse desc, a.posting_date desc, b.posting_date desc
			);
		"""
	frappe.db.sql(sql)

	#6 Create Final Stock Aging Table
	sql = """CREATE TABLE stock_aging ( 
			select item_code, item_name, item_group, brand, warehouse, company, closing_balance, 
			(sum(`0-30 Value`)+sum(`>30 Value`)+ sum(`>90 Value`)+sum(`>180 Value`)+sum(`>365 Value`)+sum(`>730 Value`)+sum(`>1095 Value`)) as balance_value, 
			sum(`0-30`) as `0-30 Qty`,sum(`0-30 Value`) as `0-30 Amount`, 
			sum(`>30`) as `>30 Qty`, sum(`>30 Value`) as `>30 Amount`,
			sum(`>90`) as `>90 Qty`, sum(`>90 Value`) as `>90 Amount`,
			sum(`>180`) as `>180 Qty`, sum(`>180 Value`) as `>180 Amount`,
			sum(`>365`) as `>365 Qty`, sum(`>365 Value`) as `>365 Amount`,
			sum(`>730`) as `>730 Qty`, sum(`>730 Value`) as `>730 Amount`,
			sum(`>1095`) as `>1095 Qty`, sum(`>1095 Value`) as `>1095 Amount`
			from Aging_Inventory_Transactions
			group by item_code, warehouse);
		"""
	frappe.db.sql(sql)

	#7 Create Index for the final Stock Aging Table
	sql = """create index idx1 on stock_aging (item_code, warehouse);"""
	frappe.db.sql(sql)

	return 0

@frappe.whitelist()
def connect_to_contribution(brand, type, region):
	#get_url_to_form(doctype, name)
	sql = f"""SELECT name FROM `tabBrand wise Sales Team Contribution`
		WHERE
		brand = '{brand}' and 
		type = '{type}' and
		region = '{region}';
	"""
	data = frappe.db.sql(sql, as_dict=1)
	if data and data[0]["name"] is not None:
		return (get_url_to_form("Brand wise Sales Team Contribution", data[0]["name"]))

@frappe.whitelist()
def notify_material_request(material_request):
		mr_o = frappe.get_doc("Material Request", material_request)
		if mr_o.docstatus == 0:
			frappe.sendmail(recipients='logistics@nest.ae',
			subject=str(mr_o.name) + " Material Request created (" + str(mr_o.sales_order)+ ")",
			message= "The subject Material Request has been created.")

@frappe.whitelist()
def send_leave_circular():
	frappe.errprint ('sending email circular **************')
	sql="""select la.name, concat(e.salutation,'. ',e.employee_name) as employee, la.from_date, la.to_date, la.leave_relievers, la.notification_sent from `tabLeave Application` la 
		inner join `tabEmployee` e on la.employee = e.name
		where la.status = 'Approved' and la.leave_type ='Annual Leave' and la.notification_sent = 0
		and la.from_date >= curdate() and la.from_date < adddate(curdate(), 5);"""
	leaves = frappe.db.sql(sql, as_dict=1)

	if leaves and leaves[0]["name"] is not None:
		for leave in leaves:
			leave_application = leave["name"]
			employee = leave["employee"]
			from_date = formatdate(str(leave["from_date"]))
			to_date = formatdate(str(leave["to_date"]))
			leave_relievers = leave["leave_relievers"]

			frappe.sendmail(recipients='nest-all@nest.ae', #husam.alkhateeb@nest.ae, nest-all@nest.ae
					subject="Leave Announcement - " + employee,
					template ='annual_leave_circular',
					args=dict(
						employee=employee,
						from_date=from_date,
						to_date=to_date,
						leave_reliefers=leave_relievers,
					),		
			)
			
			sql = "UPDATE `tabLeave Application` SET notification_sent = 1 WHERE name = '"+leave_application+"';"
			frappe.db.sql(sql)




#******************************** BONUS ACCRUAL SYSTM ************************************************************
#*******************************  ADDED 2023-04-17 ***************************************************************

@frappe.whitelist()
def make_bonus_accrual():
	#frappe.errprint('# # make_bonus_accrual CALLED')
	employees = frappe.get_all("Employee", filters={"status": "Active", "name": ['like', '2%']}, fields=["name"])
	if employees:
		for employee in employees:
			frappe.errprint(employee.name)
			#create_bonus_accrual(employee.name)
	else:
		return -1
	
@frappe.whitelist()
def create_bonus_accrual(employee):
	try:
		#  *********  MAYBE IT IS BEST TO RUN NIGHTLY AND GENERATE FOR ALL EMPLOYEES (NOT JUST CURRENT USER ID) *********
		# STEPS:
		# 1- Check if ba is available and is valid (as of today). If data is valid, then skip function and return with -1
		# 2- Else:
		# 	a- Delete all DB entries for this employee.
		#	b- Load all Bonus Settings into Variables.
		#	c- Create a new master record with the basic employee details
		#	d- Generate all child tables.
		#	e- Generate totals and Calculate Bonus
		#	f- Update all fields in the master table for this employee
		#	g- return 0

		frappe.errprint("1")
		# 1- CHECK IF DATA IS VALID, THEN SKIP AND DO NOT RE-GENERATE. DATA IN DB ARE VALID.
		ba_o = frappe.get_all("Bonus Accrual", filters={"employee": employee}, fields=["name", "valuation_date", "company"])
		frappe.errprint("2")
		if ba_o:
			newrec = 0
			frappe.errprint("3")
			name = ba_o[0].name
			ba_o = frappe.get_doc("Bonus Accrual", name)
			company = ba_o.company
			if ba_o.valuation_date == date.today:
				frappe.errprint("4")
				return -1
			else:
				frappe.errprint("5")
				# Old Data, Refresh.....
				# 	a- Delete all DB entries for this employee.
				sql = "DELETE FROM `tabBonus Target vs Actual` WHERE parent = '"+name+"'"
				frappe.db.sql(sql)
				sql = "DELETE FROM `tabBonus Stock Aging` WHERE parent = '"+name+"'"
				frappe.db.sql(sql)
				sql = "DELETE FROM `tabBonus Realized Opportunity` WHERE parent = '"+name+"'"
				frappe.db.sql(sql)
				sql = "DELETE FROM `tabBonus Overdue Receivables` WHERE parent = '"+name+"'"
				frappe.db.sql(sql)
				sql = "DELETE FROM `tabBonus Noticeable Events` WHERE parent = '"+name+"'"
				frappe.db.sql(sql)
				sql = "DELETE FROM `tabBonus Gross Profit` WHERE parent = '"+name+"'"
				frappe.db.sql(sql)
				sql = "DELETE FROM `tabBonus Gross Margin` WHERE parent = '"+name+"'"
				frappe.db.sql(sql)
				#sql = "DELETE FROM `tabBonus Accrual` WHERE name = '"+name+"'"
				#frappe.db.sql(sql)
		else:
			newrec = 1
			frappe.errprint("6")
			ba_o = frappe.new_doc("Bonus Accrual")
			company = frappe.get_value("Employee", {"employee":employee}, "company")

		frappe.errprint("7")

		#2- ELSE:
		#	b- Load all Bonus Settings into Variables.
		bonus_basis =  frappe.db.get_single_value('Bonus Settings', 'bonus_basis')
		minimum_service_period_days =  frappe.db.get_single_value('Bonus Settings', 'minimum_service_period_days')
		target_profit_margin =  frappe.db.get_single_value('Bonus Settings', 'target_profit_margin')
		maximum_base_bonus_percentage =  frappe.db.get_single_value('Bonus Settings', 'maximum_base_bonus_percentage')
		nest_annual_profit_target =  frappe.db.get_single_value('Bonus Settings', 'nest_annual_profit_target')
		nest_es_profit_target =  frappe.db.get_single_value('Bonus Settings', 'nest_es_profit_target')
		firmo_annual_profit_target =  frappe.db.get_single_value('Bonus Settings', 'firmo_annual_profit_target')
		if company == "National Engineering Services & Trading Co LLC":
			profit_target = nest_annual_profit_target
		if company == "NEST Employment Services LLC":
			profit_target = nest_es_profit_target
		if company == "Firmo Technical Petroleum Services LLC":
			profit_target = firmo_annual_profit_target
		overdue_receivable_minimum_margin_percentage =  frappe.db.get_single_value('Bonus Settings', 'overdue_receivable_minimum_margin_percentage')
		overdue_receivable_90_days_deduction_rate =  frappe.db.get_single_value('Bonus Settings', 'overdue_receivable_90_days_deduction_rate')
		overdue_receivable_180_days_deduction_rate =  frappe.db.get_single_value('Bonus Settings', 'overdue_receivable_180_days_deduction_rate')
		overdue_receivable_270_days_deduction_rate =  frappe.db.get_single_value('Bonus Settings', 'overdue_receivable_270_days_deduction_rate')
		overdue_receivable_365_days_deduction_rate =  frappe.db.get_single_value('Bonus Settings', 'overdue_receivable_365_days_deduction_rate')
		stock_aging_minimum_margin_percentage =  frappe.db.get_single_value('Bonus Settings', 'stock_aging_minimum_margin_percentage')
		stock_aging_90_days_deduction_rate =  frappe.db.get_single_value('Bonus Settings', 'stock_aging_90_days_deduction_rate')
		stock_aging_180_days_deduction_rate =  frappe.db.get_single_value('Bonus Settings', 'stock_aging_180_days_deduction_rate')
		stock_aging_365_days_deduction_rate =  frappe.db.get_single_value('Bonus Settings', 'stock_aging_365_days_deduction_rate')
		stock_aging_730_days_deduction_rate =  frappe.db.get_single_value('Bonus Settings', 'stock_aging_730_days_deduction_rate')
		exceeding_target_incentive_percentage =  frappe.db.get_single_value('Bonus Settings', 'exceeding_target_incentive_percentage')
		minimum_acceptable_achieved_percentage =  frappe.db.get_single_value('Bonus Settings', 'minimum_acceptable_achieved_percentage')
		exceeding_target_maximum_percentage =  frappe.db.get_single_value('Bonus Settings', 'exceeding_target_maximum_percentage')
		peformance_appraisal_factor_rate =  frappe.db.get_single_value('Bonus Settings', 'peformance_appraisal_factor_rate')
		major_opportunities_incentive_percentage =  frappe.db.get_single_value('Bonus Settings', 'major_opportunities_incentive_percentage')
		gross_margin_percentage =  frappe.db.get_single_value('Bonus Settings', 'gross_margin_percentage')
		estimated_revenue_from_sales =  frappe.db.get_single_value('Bonus Settings', 'estimated_revenue_from_sales')
		reduced_margin_penalty_multiplier =  frappe.db.get_single_value('Bonus Settings', 'reduced_margin_penalty_multiplier')
		net_profit_impact_factor =  frappe.db.get_single_value('Bonus Settings', 'net_profit_impact_factor')
		latest_attendance_minutes =  frappe.db.get_single_value('Bonus Settings', 'latest_attendance_minutes')
		earliest_attendance_minutes =  frappe.db.get_single_value('Bonus Settings', 'earliest_attendance_minutes')
		attendance_delay_penalty_factor =  frappe.db.get_single_value('Bonus Settings', 'attendance_delay_penalty_factor')
		customer_visits_incentive =  frappe.db.get_single_value('Bonus Settings', 'customer_visits_incentive')
		employee_noticeable_event_incident_rate =  frappe.db.get_single_value('Bonus Settings', 'employee_noticeable_event_incident_rate')
		employee_noticeable_event_incident_financial_impact_rate =  frappe.db.get_single_value('Bonus Settings', 'employee_noticeable_event_incident_financial_impact_rate')

		#	c- Create a new master record with the basic employee details
		emp_o = frappe.get_doc("Employee", employee)
		frappe.errprint("8")
		ba_o.employee = emp_o.name
		ba_o.employee_name = emp_o.employee_name
		ba_o.department = emp_o.department
		ba_o.company = emp_o.company
		ba_o.date_of_joining = emp_o.date_of_joining

		sql = """select sum(ssd.amount)*if(ssd.parentfield = 'deductions',-1,1) as total_salary 
				from `tabSalary Structure Assignment` ssa
				inner join `tabSalary Detail` ssd on ssa.salary_structure = ssd.parent where ssa.docstatus=1 and
				ssa.employee = """
		sql = sql + employee
		if bonus_basis == "Basic Salary":
			sql = sql + " and ssd.salary_component like '%Basic%'" 
		data = frappe.db.sql(sql)
		salary = data[0][0]
		ba_o.salary = salary
		valuation_date = today()
		ba_o.valuation_date = valuation_date
		fiscal_year = frappe.db.get_single_value('Global Defaults', 'current_fiscal_year')
		ba_o.fiscal_year = fiscal_year
		months_ytd = min(12,math.floor((datetime.today() - datetime(int(fiscal_year), 1,1)).days/30))
		ba_o.months_ytd = months_ytd
		ba_o.save()

		#	d- Generate all child tables.
		# 1- Sales Target vs Actual
		frappe.errprint("9")
		sql = f"""SELECT brand, `type`, region, target, actual_sales FROM
				(select st.brand, st.type, st.region, ifnull(st.allocated_target,0) target, ifnull(sa.achieved_sale,0) actual_sales from 
				(select cm.brand, cm.type, cm.region, t.total, c.allocated_percentage, (t.total*c.allocated_percentage/100) as allocated_target from `tabEmployee Sales Contribution` c 
				inner join `tabBrand wise Sales Team Contribution` cm on cm.name = c.parent
				inner join `tabBrand wise Child Table` t on t.brand = cm.brand and t.type = cm.type and t.region = cm.region
				where c.employee = '{employee}'
				) st
				left join 
				(select so.brand_reference as brand, so.project_type as type, so.sales_region region , sum(so.base_net_total) total, st.allocated_percentage, (sum(so.base_net_total)*st.allocated_percentage/100) achieved_sale
				from `tabSales Order` so
				inner join `tabSales Team` st on so.name = st.parent
				inner join `tabSales Person` sp on st.sales_person = sp.name
				where so.docstatus = '1' 
					and so.transaction_date >= '{fiscal_year}-01-01' and so.transaction_date <= '{fiscal_year}-12-31'
					and sp.employee = '{employee}'
				group by brand_reference, project_type, sales_region
				) sa
				on st.brand = sa.brand and st.type = sa.type and st.region = sa.region
				where ifnull(st.allocated_target,0)>0 
				) tva 
				order by brand, `type`, region;
		"""
		data = frappe.db.sql(sql, as_dict=1)
		if data:
			frappe.errprint("10")
			for item in data:
				ba_o.append("bonus_target_vs_actual",{
					"brand":item["brand"],
					"type": item["type"],
					"region":item["region"],
					"target":item["target"],
					"actual_sales":item["actual_sales"]
				})
			ba_o.save()

		sql = f"""SELECT sum(`target`) total_target, sum(`actual_sales`) total_actual FROM `tabBonus Target vs Actual`
				where parent = '{ba_o.name}'"""
		data = frappe.db.sql(sql)
		if data:
			frappe.errprint("11")
			ba_o.total_target = data[0][0]#['total_target']
			ba_o.total_actual = data[0][1]#['total_actual']

		# 2- Overdue Recievables
		sql = f"""SELECT `brand`, `over_90_days_amount`, `over_180_days_amount`, `over_270_days_amount`, `over_365_days_amount`, 
				`over_90_days_impact`, `over_180_days_impact`, `over_270_days_impact`, `over_365_days_impact`, 
				`brand_allocation`, `sales_additive` FROM
				(select sst.brand, ifnull(`>90`,0) over_90_days_amount, ifnull(`>180`,0) over_180_days_amount, ifnull(`>270`,0) over_270_days_amount, ifnull(`>365`,0) over_365_days_amount, 
				ifnull(osi.`>90`,0)*({overdue_receivable_90_days_deduction_rate}/100)/({overdue_receivable_minimum_margin_percentage}/100) over_90_days_impact, 
				ifnull(osi.`>180`,0)*({overdue_receivable_180_days_deduction_rate}/100)/({overdue_receivable_minimum_margin_percentage}/100) over_180_days_impact, 
				ifnull(osi.`>270`,0)*({overdue_receivable_270_days_deduction_rate}/100)/({overdue_receivable_minimum_margin_percentage}/100) over_270_days_impact, 
				ifnull(osi.`>365`,0)*({overdue_receivable_365_days_deduction_rate}/100)/({overdue_receivable_minimum_margin_percentage}/100) over_365_days_impact,
				sst.avg_allocated_percentage brand_allocation, 
				(ifnull(osi.`>90`,0)*({overdue_receivable_90_days_deduction_rate}/100)/({overdue_receivable_minimum_margin_percentage}/100)+ifnull(osi.`>180`,0)*({overdue_receivable_180_days_deduction_rate}/100)/({overdue_receivable_minimum_margin_percentage}/100)+ifnull(osi.`>270`,0)*({overdue_receivable_270_days_deduction_rate}/100)/({overdue_receivable_minimum_margin_percentage}/100)+ifnull(osi.`>365`,0)*({overdue_receivable_365_days_deduction_rate}/100)/({overdue_receivable_minimum_margin_percentage}/100))*sst.avg_allocated_percentage/100*-1 sales_additive
				from (
				select brand, if(sum(total)= 0,0,ifnull(sum(allotment)/sum(total),0)) avg_allocated_percentage from
				(
				select cm.brand, cm.type, cm.region, c.allocated_percentage, t.total, c.allocated_percentage * t.total allotment
				from `tabEmployee Sales Contribution` c 
				inner join `tabBrand wise Sales Team Contribution` cm on cm.name = c.parent
				inner join `tabBrand wise Child Table` t on t.brand = cm.brand and t.type = cm.type and t.region = cm.region
				where c.employee = {employee}
				) st group by st.brand ) sst
				left join 
				(
				select brand, sum(`>90`) as `>90`, sum(`>180`) as `>180`, sum(`>270`) as `>270`, sum(`>365`) as `>365`
				from
				(
				select si.name, si.customer, so.brand, length(so.brand) l, si.status, si.posting_date, datediff(curdate(), si.posting_date)+1 as aged_days, si.base_net_total,
				if((datediff(curdate(), si.posting_date)+1)>90 and (datediff(curdate(), si.posting_date)+1)<=180,si.base_net_total,0) as `>90`,
				if((datediff(curdate(), si.posting_date)+1)>180 and (datediff(curdate(), si.posting_date)+1)<=270,si.base_net_total,0) as `>180`,
				if((datediff(curdate(), si.posting_date)+1)>270 and (datediff(curdate(), si.posting_date)+1)<=365,si.base_net_total,0) as `>270`,
				if((datediff(curdate(), si.posting_date)+1)>365,si.base_net_total,0) as `>365`
				from `tabSales Order` so
				inner join `tabSales Invoice` si on so.name = si.sales_order
				where si.status in ('Unpaid', 'Unpaid and Discounted', 'Overdue', 'Overdue and Discounted')
				and (datediff(curdate(), si.posting_date)+1)>90 and length(ifnull(so.brand,''))>1 
				) os group by brand
				) osi
				on sst.brand = osi.brand
				where ifnull(`>90`,0)+ifnull(`>180`,0)+ifnull(`>270`,0)+ifnull(`>365`,0)) odr
				order by brand;"""

		data = frappe.db.sql(sql, as_dict=1)
		if data:
			frappe.errprint("12")
			for item in data:
				ba_o.append("bonus_overdue_receivables",{
					"brand": item["brand"],
					"over_90_days_amount": item["over_90_days_amount"],
					"over_180_days_amount": item["over_180_days_amount"],
					"over_270_days_amount": item["over_270_days_amount"],
					"over_365_days_amount": item["over_365_days_amount"],
					"over_90_days_impact": item["over_90_days_impact"],
					"over_180_days_impact": item["over_180_days_impact"],
					"over_270_days_impact": item["over_270_days_impact"],
					"over_365_days_impact": item["over_365_days_impact"],
					"brand_allocation": item["brand_allocation"],
					"sales_additive": item["sales_additive"]
				})
			ba_o.save()

		sql = f"""SELECT sum(sales_additive) as total_deductions
				FROM `tabBonus Overdue Receivables`
				where parent ='{ba_o.name}'"""
		data = frappe.db.sql(sql)
		if data:
			frappe.errprint("13")
			ba_o.overdue_receivables_total_deductions = data[0][0]#['total_deductions']

		# 3- Stock Aging
		sql = f"""SELECT `brand`, `over_90_days_amount`, `over_180_days_amount`, `over_365_days_amount`, `over_730_days_amount`, 
				`over_90_days_impact`, `over_180_days_impact`, `over_365_days_impact`, `over_730_days_impact`, `brand_allocation`, `sales_additive`
				FROM 
				(select sst.brand, ifnull(`>90 Amount`,0) over_90_days_amount, ifnull(`>180 Amount`,0) over_180_days_amount, ifnull(`>365 Amount`,0) over_365_days_amount, ifnull(`>730 Amount`,0) over_730_days_amount, 
				ifnull(stk.`>90 Amount`,0)*({stock_aging_90_days_deduction_rate}/100)/({stock_aging_minimum_margin_percentage}/100) over_90_days_impact, ifnull(stk.`>180 Amount`,0)*({stock_aging_180_days_deduction_rate}/100)/({stock_aging_minimum_margin_percentage}/100) over_180_days_impact, 
				ifnull(stk.`>365 Amount`,0)*({stock_aging_365_days_deduction_rate}/100)/({stock_aging_minimum_margin_percentage}/100) over_365_days_impact, ifnull(stk.`>730 Amount`,0)*({stock_aging_730_days_deduction_rate}/100)/({stock_aging_minimum_margin_percentage}/100) over_730_days_impact,
				sst.avg_allocated_percentage brand_allocation, 
				(ifnull(stk.`>90 Amount`,0)*({stock_aging_90_days_deduction_rate}/100)/({stock_aging_minimum_margin_percentage}/100)+ifnull(stk.`>180 Amount`,0)*({stock_aging_180_days_deduction_rate}/100)/({stock_aging_minimum_margin_percentage}/100)+ifnull(stk.`>365 Amount`,0)*({stock_aging_365_days_deduction_rate}/100)/({stock_aging_minimum_margin_percentage}/100)+ifnull(stk.`>730 Amount`,0)*({stock_aging_730_days_deduction_rate}/100)/({stock_aging_minimum_margin_percentage}/100))*sst.avg_allocated_percentage/100*-1 sales_additive
				from (
				select brand, if(sum(total)=0,0,ifnull(sum(allotment)/sum(total),0)) avg_allocated_percentage from
				(
				select cm.brand, cm.type, cm.region, c.allocated_percentage, t.total, c.allocated_percentage * t.total allotment
				from `tabEmployee Sales Contribution` c 
				inner join `tabBrand wise Sales Team Contribution` cm on cm.name = c.parent
				inner join `tabBrand wise Child Table` t on t.brand = cm.brand and t.type = cm.type and t.region = cm.region
				where c.employee = '{employee}'
				) st group by st.brand ) sst
				left join 
				(
				select brand, sum(`>90 Amount`) as `>90 Amount`, sum(`>180 Amount`) as `>180 Amount`,
				sum(`>365 Amount`) as `>365 Amount`, (sum(`>730 Amount`)+sum(`>1095 Amount`)) as `>730 Amount`
				from stock_aging
				group by brand
				) stk
				on sst.brand = stk.brand
				where ifnull(`>90 Amount`,0)+ifnull(`>180 Amount`,0)+ifnull(`>365 Amount`,0)+ifnull(`>730 Amount`,0)) sa
				order by brand;"""

		data = frappe.db.sql(sql, as_dict=1)
		if data:
			frappe.errprint("14")
			for item in data:
				ba_o.append("bonus_stock_aging",{
					"brand": item["brand"],
					"over_90_days_amount": item["over_90_days_amount"],
					"over_180_days_amount": item["over_180_days_amount"],
					"over_365_days_amount": item["over_365_days_amount"],
					"over_730_days_amount": item["over_730_days_amount"],
					"over_90_days_impact": item["over_90_days_impact"],
					"over_180_days_impact": item["over_180_days_impact"],
					"over_365_days_impact": item["over_365_days_impact"],
					"over_730_days_impact": item["over_730_days_impact"],
					"brand_allocation": item["brand_allocation"],
					"sales_additive": item["sales_additive"],
				})
			ba_o.save()

		sql = f"""SELECT sum(sales_additive) as total_deductions
				FROM `tabBonus Stock Aging`
				where parent ='{ba_o.name}'"""
		data = frappe.db.sql(sql)
		if data:
			frappe.errprint("15")
			ba_o.stock_aging_total_deductions = data[0][0]#['total_deductions']

		# 4- Realized Opportunities
		sql = f"""SELECT `opportunity`, `quotation`, `sales_order`, `so_base_net_total`, `purchase_order`, `po_base_net_total`, 
				`gross_margin`, `excess_gross_margin`, `additive_rate`, `bonus_additive`
				FROM
				(select op.name opportunity, qt.name quotation, so.name sales_order, so.base_net_total so_base_net_total, po.name purchase_order, po.base_net_total po_base_net_total, 
					(so.base_net_total/po.base_net_total - 1)*100 gross_margin, (so.base_net_total/po.base_net_total - (1+{target_profit_margin}/100))*100 excess_gross_margin,
					{major_opportunities_incentive_percentage}/100 additive_rate,
					if((so.base_net_total/po.base_net_total - (1+{target_profit_margin}/100))>=0,1,2)*{major_opportunities_incentive_percentage}/100*(so.base_net_total/po.base_net_total - (1+{target_profit_margin}/100))*abs(so.base_net_total-po.base_net_total)*st.allocated_percentage/100 bonus_additive
				from `tabSales Order` so inner Join `tabPurchase Order` po on so.name = po.sales_order_no
				inner join `tabSales Team` st on so.name = st.parent
				inner join `tabSales Person` sp on st.sales_person = sp.name
				inner join `tabSales Order Item` soi on soi.parent = so.name
				inner join `tabQuotation` qt on qt.name = soi.prevdoc_docname
				inner join `tabOpportunity` op on qt.opportunity = op.name 
				where so.docstatus = '1' 
					and so.transaction_date >= '{fiscal_year}-01-01' and so.transaction_date <= '{fiscal_year}-12-31'
					and sp.employee = '{employee}') ro 
				order by `opportunity`, `quotation`, `sales_order`;"""
		
		data = frappe.db.sql(sql, as_dict=1)
		if data:
			frappe.errprint("16")
			for item in data:
				ba_o.append("bonus_realized_opportunity",{
					"Opportunity": item["Opportunity"],
					"Quotation": item["Quotation"],
					"sales_order": item["sales_order"],
					"so_base_net_total": item["so_base_net_total"],
					"purchase_order": item["purchase_order"],
					"po_base_net_total": item["po_base_net_total"],
					"gross_margin": item["gross_margin"],
					"excess_gross_margin": item["excess_gross_margin"],
					"additive_rate": item["additive_rate"],
					"bonus_additive": item["bonus_additive"]
				})
			ba_o.save()
		
		sql = f"""SELECT sum(bonus_additive) as total_deductions
				FROM `tabBonus Realized Opportunity`
				where parent ='{ba_o.name}'"""
		data = frappe.db.sql(sql)
		if data:
			frappe.errprint("17")
			ba_o.realized_opportunities_bonus_additive = data[0][0]#['total_deductions']

		# 5- Gross Margin
		sql = f"""select so.name sales_order, so.base_net_total so_base_net_total, po.name purchase_order, sum(po.base_net_total) po_base_net_total, 
					(so.base_net_total/sum(po.base_net_total) - 1)*100 gross_margin, 
					(so.base_net_total/sum(po.base_net_total) - (1+{target_profit_margin}/100))*100 excess_gross_margin,
					ec.allocated_percentage brand_allocation,
					2 additive_rate,
					if((so.base_net_total/sum(po.base_net_total) - (1+{target_profit_margin}/100))>=0,1,{reduced_margin_penalty_multiplier})*{gross_margin_percentage}/100*(so.base_net_total/sum(po.base_net_total) 
					- (1+{target_profit_margin}/100))*abs(so.base_net_total-sum(po.base_net_total))*ec.allocated_percentage/100 bonus_additive
					from `tabSales Order` so inner Join `tabPurchase Order` po on so.name = po.sales_order_no
					inner join `tabBrand wise Sales Team Contribution` tc on tc.brand = so.brand_reference and tc.type = so.project_type and tc.region = so.sales_region
					inner join `tabEmployee Sales Contribution` ec on ec.parent = tc.name
					where so.docstatus = '1' and po.docstatus = '1' 
						and so.transaction_date >= '{fiscal_year}-01-01' and so.transaction_date <= '{fiscal_year}-12-31'
						and ec.employee = '{employee}' and so.brand_reference not like 'NEST%'
						group by so.name
						order by so.name;
				"""
		data = frappe.db.sql(sql, as_dict=1)
		if data:
			frappe.errprint("18")
			for item in data:
				ba_o.append("bonus_gross_margin",{
					"sales_order": item["sales_order"],
					"so_base_net_total": item["so_base_net_total"],
					"purchase_order": item["purchase_order"],
					"po_base_net_total": item["po_base_net_total"],
					"gross_margin": item["gross_margin"],
					"excess_gross_margin": item["excess_gross_margin"],
					"brand_allocation": item["brand_allocation"],
					"additive_rate": item["additive_rate"],
					"bonus_additive": item["bonus_additive"]
				})
			ba_o.save()

		sql = f"""SELECT (sum(so_base_net_total)/sum(po_base_net_total) - 1)*100 average_gross_margin, sum(bonus_additive) as total_deductions
				FROM `tabBonus Gross Margin`
				where parent ='{ba_o.name}'"""
		data = frappe.db.sql(sql)
		if data:
			frappe.errprint("19")
			ba_o.average_gross_margin = data[0][0]
			ba_o.gross_margin_bonus_additive = data[0][1]#['total_deductions']

		# 6- Gross Revenue
		sql = f"""select brand, type, region, sales_target, estimated_revenue, actual_revenue, brand_allocation, additive_rate, 
				(actual_revenue - estimated_revenue)*brand_allocation*target_profit*additive_rate bonus_additive
				from
				(select cm.brand, cm.type, cm.region, ifnull(t.total,0) sales_target, 
					(t.total*c.allocated_percentage/100)*{estimated_revenue_from_sales}/100*{months_ytd}/12 estimated_revenue,
					sum(ifnull(si.base_net_total,0))*c.allocated_percentage/100 actual_revenue, 
					c.allocated_percentage/100 brand_allocation, 
					{target_profit_margin}/100 target_profit,
					{net_profit_impact_factor}/100 additive_rate
					from `tabEmployee Sales Contribution` c 
					inner join `tabBrand wise Sales Team Contribution` cm on cm.name = c.parent
					inner join `tabBrand wise Child Table` t on t.brand = cm.brand and t.type = cm.type and t.region = cm.region
					left join `tabSales Order` so on so.brand = cm.brand and so.project_type = cm.type and so.sales_region = cm.region
					left join `tabSales Invoice` si on so.name = si.sales_order
					where c.employee = '{employee}'
				group by cm.brand, cm.type, cm.region
				) gr
				order by brand, type, region;
				"""
		data = frappe.db.sql(sql, as_dict=1)
		if data:
			frappe.errprint("20")
			for item in data:
				ba_o.append("bonus_gross_profit",{
					"brand": item["brand"],
					"type": item["type"],
					"region":item["region"],
					"sales_target": item["sales_target"],
					"estimated_revenue": item["estimated_revenue"],
					"actual_revenue": item["actual_revenue"],
					"brand_allocation": item["brand_allocation"],
					"additive_rate": item["additive_rate"],
					"bonus_additive": item["bonus_additive"]
				})
			ba_o.save()

		sql = f"""SELECT sum(bonus_additive) as total_deductions
				FROM `tabBonus Gross Profit`
				where parent ='{ba_o.name}'"""
		data = frappe.db.sql(sql)
		if data:
			frappe.errprint("21")
			ba_o.gross_profit_bonus_additive = data[0][0]#['total_deductions']

		# 7- Noticeable Events
		sql = f""" SELECT `noticeable_event`, `date`, `event`, `event_type`, `financial_impact`, `bonus_additive`
			FROM
			(select name noticeable_event, date, event, event_type, financial_impact,
			(if(financial_impact = 0, {employee_noticeable_event_incident_rate},greatest({employee_noticeable_event_incident_rate}, 
			{employee_noticeable_event_incident_financial_impact_rate}/100*financial_impact))*if(event_type='Negative',-1,1)) bonus_additive
			from `tabEmployee Noticeable Event`
			where 
				employee = '{employee}' and 
				status = 'Approved' and 
				date >= '{fiscal_year}-01-01' and date <= '{fiscal_year}-12-31'
			) ne
			order by date;"""
		data = frappe.db.sql(sql, as_dict=1)
		if data:
			frappe.errprint("22")
			for item in data:
				ba_o.append("bonus_noticeable_events",{
					"noticeable_event": item["noticeable_event"],
					"date": item["date"],
					"event": item["event"],
					"event_type": item["event_type"],
					"financial_impact": item["financial_impact"],
					"bonus_additive": item["bonus_additive"],
				})
			ba_o.save()

		sql = f"""SELECT sum(bonus_additive) as total_deductions
				FROM `tabBonus Noticeable Events`
				where parent ='{ba_o.name}'"""
		data = frappe.db.sql(sql)
		if data:
			frappe.errprint("23")
			ba_o.noticeable_events_bonus_additive = data[0][0]#['total_deductions']

		# 8- Sales Visits
		sql = f"""select count(*) number_of_sales_visits, count(*)*{customer_visits_incentive} sales_visits_bonus_additive 
				from `tabSales Team Visit Log` where employee = '{employee}'"""
		data = frappe.db.sql(sql)
		if data:
			frappe.errprint("24")
			ba_o.number_of_sales_visits = data[0][0]#['number_of_sales_visits']
			ba_o.sales_visits_bonus_additive = data[0][1]#['sales_visits_bonus_additive']

		# 9- Attendance
		sql = "select value from tabSingles where doctype='Bonus Settings' and field='attendance_delay_penalty_factor'"
		data = frappe.db.sql(sql)
		if data:
			frappe.errprint("25")
			attendance_delay_penalty_factor = data[0][0]
		
		sql = f"""select ifnull(sum(delay),0) ytd_late_minutes, ifnull(sum(delay),0)*{salary}*({attendance_delay_penalty_factor}) attendance_bonus_additive # 7000 is the total Salary
				from
				(
				select name, employee, attendance_date, clock_in, standard_clock_in,  
				#=IF(TimeDiff<0,MAX(TimeDiff,{earliest_attendance_minutes}), IF(TimeDiff>{latest_attendance_minutes}, TimeDiff-{latest_attendance_minutes},0))
				if(TIMESTAMPDIFF(MINUTE, standard_clock_in, clock_in)<0, greatest(TIMESTAMPDIFF(MINUTE, standard_clock_in, clock_in),{earliest_attendance_minutes}), 
				if(TIMESTAMPDIFF(MINUTE, standard_clock_in, clock_in)>{latest_attendance_minutes}, TIMESTAMPDIFF(MINUTE, standard_clock_in, clock_in)-{latest_attendance_minutes},0))  delay
				from `tabAttendance` 
				where 
					status = 'Present'  
					and attendance_date >= '{fiscal_year}-01-01' and attendance_date <= '{fiscal_year}-12-31' 
					and employee = '{employee}'
				) att;"""
		
		data = frappe.db.sql(sql)
		if data:
			frappe.errprint("26")
			ba_o.ytd_late_minutes = data[0][0]#['ytd_late_minutes']
			ba_o.attendance_bonus_additive = data[0][1]#['attendance_bonus_additive']

		# 10- Performance Appraisal
		sql = f"""select average_performance_appraisal, ((average_performance_appraisal-3)*{peformance_appraisal_factor_rate}) performance_appraisal_factor 
				from
				( 
				select ifnull((select (attitude+initiative+dependability+work_quality+work_quantity+knowledge_of_job+
				team_play+organization_ability+judgement+responsibility+overall_rating)/11 
				from `tabNEST Performance Appraisal` 
				where employee = '{employee}' and year = ({fiscal_year})-1),3) average_performance_appraisal
				) pa;"""
		
		data = frappe.db.sql(sql)
		if data:
			frappe.errprint("27")
			ba_o.average_performance_appraisal = data[0][0] #['average_performance_appraisal']
			ba_o.performance_appraisal_factor = data[0][1]+100 #['performance_appraisal_factor']

		# ******* SUMMARY ***********
		sql = f"""select (sum(credit)-sum(debit)) as net_profit from `tabGL Entry` gl
				inner join `tabEmployee` e on gl.company = e.company
				where account in (select name from tabAccount where root_type in ('Income', 'Expense') and is_group =0) 
				and fiscal_year = 2023 and is_opening = 'No'
				and e.name = '{employee}';
		"""
		data = frappe.db.sql(sql)
		if data:
			frappe.errprint("28")
			ba_o.net_profit = data[0][0]#['net_profit']
		else:
			frappe.errprint("29")
			ba_o.net_profit = 0
		
		base_bonus = min(ba_o.net_profit/(profit_target*months_ytd/12), maximum_base_bonus_percentage/100)*salary
		ba_o.base_bonus = base_bonus

		adjusted_actual_sales =ba_o.total_actual + ba_o.overdue_receivables_total_deductions + ba_o.stock_aging_total_deductions
		ba_o.adjusted_actual_sales = adjusted_actual_sales

		#=If(Years_of_service < 1,0,1)
		#(datetime.today() - datetime(int(fiscal_year), 1,1)).days
		doj = datetime.strptime(str(ba_o.date_of_joining), "%Y-%m-%d")
		if(datetime.today()-doj).days <= int(minimum_service_period_days):
			frappe.errprint("30")
			ba_o.service_period_factor = 0
		else:
			frappe.errprint("31")
			ba_o.service_period_factor = 100
		
		#'=IF(Target=0,1,IF(AdjActual>Target,MIN(1+(AdjActual/Target-1)*1.5,3), IF(AdjActual/Target<80%,0, AdjActual/Target)))
		if ba_o.total_target == 0:
			frappe.errprint("32")
			ba_o.actual_vs_target_bonus_factor = 100
		else:
			if adjusted_actual_sales > ba_o.total_target:
				frappe.errprint("33")
				ba_o.actual_vs_target_bonus_factor = min(1+(adjusted_actual_sales/ba_o.total_target)*exceeding_target_incentive_percentage/100,exceeding_target_maximum_percentage/100)
			elif (adjusted_actual_sales/ba_o.total_target)<minimum_acceptable_achieved_percentage/100:
				frappe.errprint("34")
				ba_o.actual_vs_target_bonus_factor = 0
			else:
				frappe.errprint("35")
				ba_o.actual_vs_target_bonus_factor = adjusted_actual_sales/ba_o.total_target*100


		#=(AvgPerformanceAppraisal-3)*AdjustmentRate+1
		#done above

		ba_o.total_bonus_additives = float(ba_o.realized_opportunities_bonus_additive or 0)+ \
			float(ba_o.gross_margin_bonus_additive or 0) + \
			float(ba_o.gross_profit_bonus_additive or 0) + \
			float(ba_o.noticeable_events_bonus_additive or 0) + \
			float(ba_o.sales_visits_bonus_additive or 0) + \
			float(ba_o.attendance_bonus_additive or 0)

		ba_o.total_accrued_bonus = (base_bonus+ba_o.total_bonus_additives)*ba_o.service_period_factor/100*ba_o.actual_vs_target_bonus_factor/100*ba_o.performance_appraisal_factor/100

		ba_o.save()
		frappe.db.commit()
		frappe.errprint("36")
		return 0

	except Exception as e:
		return e