# Copyright (c) 2013, QCS and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from summer_note.common import create_stock_aging

def execute(filters=None):
	# CHECK FILTERS
	if not filters:
		columns, data = [], []
		return columns, data
	
	group_by=""
	if filters.get("group_by"):
		group_by = filters.get("group_by")

	company = ""
	if filters.get("company"):
		company = filters.get("company")

	# PREPARE COLUMN LIST
	if group_by == "Item Code":
		columns = [
			{'label': _('Company'), 'fieldname': 'company', 'fieldtype': 'Link', 'options': 'company', 'width': 100}, 
			{'label': _('Item Code'), 'fieldname': 'item_code', 'fieldtype': 'Link', 'options': 'item', 'width': 100}, 
			{'label': _('Item Name'), 'fieldname': 'item_name', 'fieldtype': 'Data', 'width': 100}, 
			{'label': _('Item Group'), 'fieldname': 'item_group', 'fieldtype': 'Link', 'options': 'item group', 'width': 100}, 
			{'label': _('Brand'), 'fieldname': 'brand', 'fieldtype': 'Link', 'options': 'brand', 'width': 100}, 
			{'label': _('Warehouse'), 'fieldname': 'warehouse', 'fieldtype': 'Link', 'options': 'warehouse', 'width': 100}, 
			{'label': _('Balance Qty'), 'fieldname': 'closing_balance', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('Balance Value'), 'fieldname': 'balance_value', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('0-30 Qty'), 'fieldname': '0-30 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('0-30 Amount'), 'fieldname': '0-30 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>30 Qty'), 'fieldname': '>30 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>30 Amount'), 'fieldname': '>30 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>90 Qty'), 'fieldname': '>90 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>90 Amount'), 'fieldname': '>90 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>180 Qty'), 'fieldname': '>180 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>180 Amount'), 'fieldname': '>180 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>365 Qty'), 'fieldname': '>365 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>365 Amount'), 'fieldname': '>365 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>730 Qty'), 'fieldname': '>730 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>730 Amount'), 'fieldname': '>730 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>1095 Qty'), 'fieldname': '>1095 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>1095 Amount'), 'fieldname': '>1095 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}
		]
	elif group_by == "Item Group":
		columns = [
			{'label': _('Company'), 'fieldname': 'company', 'fieldtype': 'Link', 'options': 'company', 'width': 100}, 
			{'label': _('Item Group'), 'fieldname': 'item_group', 'fieldtype': 'Link', 'options': 'item group', 'width': 100}, 
			{'label': _('Warehouse'), 'fieldname': 'warehouse', 'fieldtype': 'Link', 'options': 'warehouse', 'width': 100}, 
			{'label': _('Balance Qty'), 'fieldname': 'closing_balance', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('Balance Value'), 'fieldname': 'balance_value', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('0-30 Qty'), 'fieldname': '0-30 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('0-30 Amount'), 'fieldname': '0-30 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>30 Qty'), 'fieldname': '>30 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>30 Amount'), 'fieldname': '>30 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>90 Qty'), 'fieldname': '>90 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>90 Amount'), 'fieldname': '>90 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>180 Qty'), 'fieldname': '>180 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>180 Amount'), 'fieldname': '>180 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>365 Qty'), 'fieldname': '>365 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>365 Amount'), 'fieldname': '>365 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>730 Qty'), 'fieldname': '>730 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>730 Amount'), 'fieldname': '>730 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>1095 Qty'), 'fieldname': '>1095 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>1095 Amount'), 'fieldname': '>1095 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}
		]
	elif group_by == "Brand":
		columns = [
			{'label': _('Brand'), 'fieldname': 'brand', 'fieldtype': 'Link', 'options': 'brand', 'width': 100}, 
			{'label': _('Balance Qty'), 'fieldname': 'closing_balance', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('Balance Value'), 'fieldname': 'balance_value', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('0-30 Qty'), 'fieldname': '0-30 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('0-30 Amount'), 'fieldname': '0-30 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>30 Qty'), 'fieldname': '>30 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>30 Amount'), 'fieldname': '>30 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>90 Qty'), 'fieldname': '>90 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>90 Amount'), 'fieldname': '>90 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>180 Qty'), 'fieldname': '>180 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>180 Amount'), 'fieldname': '>180 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>365 Qty'), 'fieldname': '>365 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>365 Amount'), 'fieldname': '>365 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>730 Qty'), 'fieldname': '>730 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>730 Amount'), 'fieldname': '>730 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>1095 Qty'), 'fieldname': '>1095 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>1095 Amount'), 'fieldname': '>1095 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}
		]
	elif group_by == "Brand and Warehouse":
		columns = [
			{'label': _('Brand'), 'fieldname': 'brand', 'fieldtype': 'Link', 'options': 'brand', 'width': 100}, 
			{'label': _('Warehouse'), 'fieldname': 'warehouse', 'fieldtype': 'Link', 'options': 'warehouse', 'width': 100}, 
			{'label': _('Balance Qty'), 'fieldname': 'closing_balance', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('Balance Value'), 'fieldname': 'balance_value', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('0-30 Qty'), 'fieldname': '0-30 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('0-30 Amount'), 'fieldname': '0-30 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>30 Qty'), 'fieldname': '>30 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>30 Amount'), 'fieldname': '>30 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>90 Qty'), 'fieldname': '>90 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>90 Amount'), 'fieldname': '>90 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>180 Qty'), 'fieldname': '>180 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>180 Amount'), 'fieldname': '>180 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>365 Qty'), 'fieldname': '>365 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>365 Amount'), 'fieldname': '>365 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>730 Qty'), 'fieldname': '>730 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>730 Amount'), 'fieldname': '>730 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>1095 Qty'), 'fieldname': '>1095 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>1095 Amount'), 'fieldname': '>1095 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}
		]
	elif group_by == "Warehouse":
		columns = [
			{'label': _('Company'), 'fieldname': 'company', 'fieldtype': 'Link', 'options': 'company', 'width': 100}, 
			{'label': _('Warehouse'), 'fieldname': 'warehouse', 'fieldtype': 'Link', 'options': 'warehouse', 'width': 100}, 
			{'label': _('Balance Qty'), 'fieldname': 'closing_balance', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('Balance Value'), 'fieldname': 'balance_value', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('0-30 Qty'), 'fieldname': '0-30 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('0-30 Amount'), 'fieldname': '0-30 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>30 Qty'), 'fieldname': '>30 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>30 Amount'), 'fieldname': '>30 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>90 Qty'), 'fieldname': '>90 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>90 Amount'), 'fieldname': '>90 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>180 Qty'), 'fieldname': '>180 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>180 Amount'), 'fieldname': '>180 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>365 Qty'), 'fieldname': '>365 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>365 Amount'), 'fieldname': '>365 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>730 Qty'), 'fieldname': '>730 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>730 Amount'), 'fieldname': '>730 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, 
			{'label': _('>1095 Qty'), 'fieldname': '>1095 Qty', 'fieldtype': 'Int', 'width': 100}, 
			{'label': _('>1095 Amount'), 'fieldname': '>1095 Amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100} 
		]

	# PREPARE DATA
	if group_by == "Item Code":
		sql ="""select `company`, `item_code`, `item_name`, `item_group`, `brand`, `warehouse`, `closing_balance`, `balance_value`, 
			`0-30 Qty`, `0-30 Amount`, `>30 Qty`, `>30 Amount`, `>90 Qty`, `>90 Amount`, 
			`>180 Qty`, `>180 Amount`, `>365 Qty`, `>365 Amount`, `>730 Qty`, `>730 Amount`, `>1095 Qty`, `>1095 Amount`
			from stock_aging """
		if len(company)>0:
			sql = sql + "WHERE company = '" + str(company) + "' "
		sql = sql + "order by company desc, item_code, warehouse desc;"
		data = frappe.db.sql(sql,  as_dict=1)
	elif group_by == "Item Group":
		sql ="""select company, item_group, warehouse, 
			sum(closing_balance) as closing_balance, 
			sum(balance_value) as balance_value,
			sum(`0-30 Qty`) as `0-30 Qty`, sum(`0-30 Amount`) as `0-30 Amount`,
			sum(`>30 Qty`) as `>30 Qty`, sum(`>30 Amount`) as `>30 Amount`,
			sum(`>90 Qty`) as `>90 Qty`, sum(`>90 Amount`) as `>90 Amount`,
			sum(`>180 Qty`) as `>180 Qty`, sum(`>180 Amount`) as `>180 Amount`,
			sum(`>365 Qty`) as `>365 Qty`, sum(`>365 Amount`) as `>365 Amount`,
			sum(`>730 Qty`) as `>730 Qty`, sum(`>730 Amount`) as `>730 Amount`,
			sum(`>1095 Qty`) as `>1095 Qty`, sum(`>1095 Amount`) as `>1095 Amount`
			from stock_aging """
		if len(company)>0:
			sql = sql + "WHERE company = '" + str(company) + "' "
		sql = sql + """group by company, item_group, warehouse order by company desc, item_group, warehouse desc;"""
		data = frappe.db.sql(sql,  as_dict=1)
	elif group_by == "Brand":
		sql ="""select brand,  
			sum(closing_balance) as closing_balance, 
			sum(balance_value) as balance_value,
			sum(`0-30 Qty`) as `0-30 Qty`, sum(`0-30 Amount`) as `0-30 Amount`,
			sum(`>30 Qty`) as `>30 Qty`, sum(`>30 Amount`) as `>30 Amount`,
			sum(`>90 Qty`) as `>90 Qty`, sum(`>90 Amount`) as `>90 Amount`,
			sum(`>180 Qty`) as `>180 Qty`, sum(`>180 Amount`) as `>180 Amount`,
			sum(`>365 Qty`) as `>365 Qty`, sum(`>365 Amount`) as `>365 Amount`,
			sum(`>730 Qty`) as `>730 Qty`, sum(`>730 Amount`) as `>730 Amount`,
			sum(`>1095 Qty`) as `>1095 Qty`, sum(`>1095 Amount`) as `>1095 Amount`
			from stock_aging """
		if len(company)>0:
			sql = sql + "WHERE company = '" + str(company) + "' "
		sql = sql + """group by brand order by brand;"""
		data = frappe.db.sql(sql,  as_dict=1)
	elif group_by == "Brand and Warehouse":
		sql ="""select brand, warehouse,  
			sum(closing_balance) as closing_balance, 
			sum(balance_value) as balance_value,
			sum(`0-30 Qty`) as `0-30 Qty`, sum(`0-30 Amount`) as `0-30 Amount`,
			sum(`>30 Qty`) as `>30 Qty`, sum(`>30 Amount`) as `>30 Amount`,
			sum(`>90 Qty`) as `>90 Qty`, sum(`>90 Amount`) as `>90 Amount`,
			sum(`>180 Qty`) as `>180 Qty`, sum(`>180 Amount`) as `>180 Amount`,
			sum(`>365 Qty`) as `>365 Qty`, sum(`>365 Amount`) as `>365 Amount`,
			sum(`>730 Qty`) as `>730 Qty`, sum(`>730 Amount`) as `>730 Amount`,
			sum(`>1095 Qty`) as `>1095 Qty`, sum(`>1095 Amount`) as `>1095 Amount`
			from stock_aging """
		if len(company)>0:
			sql = sql + "WHERE company = '" + str(company) + "' "
		sql = sql + """group by brand, warehouse order by brand, warehouse desc;"""
		data = frappe.db.sql(sql,  as_dict=1)
	elif group_by == "Warehouse":
		sql ="""select company, warehouse, 
			sum(closing_balance) as closing_balance, 
			sum(balance_value) as balance_value,
			sum(`0-30 Qty`) as `0-30 Qty`, sum(`0-30 Amount`) as `0-30 Amount`,
			sum(`>30 Qty`) as `>30 Qty`, sum(`>30 Amount`) as `>30 Amount`,
			sum(`>90 Qty`) as `>90 Qty`, sum(`>90 Amount`) as `>90 Amount`,
			sum(`>180 Qty`) as `>180 Qty`, sum(`>180 Amount`) as `>180 Amount`,
			sum(`>365 Qty`) as `>365 Qty`, sum(`>365 Amount`) as `>365 Amount`,
			sum(`>730 Qty`) as `>730 Qty`, sum(`>730 Amount`) as `>730 Amount`,
			sum(`>1095 Qty`) as `>1095 Qty`, sum(`>1095 Amount`) as `>1095 Amount`
			from stock_aging """
		if len(company)>0:
			sql = sql + "WHERE company = '" + str(company) + "' "
		sql = sql + """group by warehouse order by company desc, warehouse desc;"""
		data = frappe.db.sql(sql,  as_dict=1)

	return columns, data