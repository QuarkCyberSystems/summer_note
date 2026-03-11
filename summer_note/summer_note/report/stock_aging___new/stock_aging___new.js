// Copyright (c) 2016, QCS and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Stock Aging - New"] = {
	"filters": [
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"reqd": 0,
			"default": "National Engineering Services & Trading Co LLC"
		},
		{
			"fieldname":"to_date",
			"label": __("As On Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
			"reqd": 1
		},
		{
			"fieldname":"group_by",
			"label": __("Group By"),
			"fieldtype": "Select",
			"options": "Item Code\nItem Group\nBrand\nBrand and Warehouse\nWarehouse",
			"reqd": 1,
			"default": "Item Code"
		},
	]
};
