// Copyright (c) 2016, QCS and contributors
// For license information, please see license.txt
/* eslint-disable */
async function show_progress() {
    for (let i = 0; i <= 50; i++) {
		frappe.show_progress('Loading..', i*2, 100, 'Please wait');
		await new Promise(r => setTimeout(r, 40));
    }
};

frappe.query_reports["Stock Aging - New"] = {
	"filters": [
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"reqd": 0,
			"default": ""
		},
		{
			"fieldname":"group_by",
			"label": __("Group By"),
			"fieldtype": "Select",
			"options": "Item Code\nItem Group\nBrand\nBrand and Warehouse\nWarehouse",
			"reqd": 1,
			"default": ""
		},
	],

	onload: function(report) {
		//console.log ('********* REPORT ONLOAD **********');
		show_progress();
		frappe.call({
			method:"summer_note.common.create_stock_aging",
			callback: function(r) 
			{
				if(r.message === 0) 
				{
					//console.log ('********* ONLOAD  CREATE TABLE FINISHED **********');
					frappe.show_progress('Loading..', 100, 100, 'Please wait');
					frappe.msgprint({
						title: __('Report Generated Successfully'),
						indicator: 'green',
						message: __('Please select the report filters.')
					});

				}
			}
		});
	}
};
