// Copyright (c) 2023, QCS and contributors
// For license information, please see license.txt

frappe.ui.form.on('Brand wise Sales Team Contribution', {
	setup: function(frm) {
		frm.set_query("brand", function() {
			return{
				"filters": {
					"type": ["in", ["Principal"]],
				}
			}
		});		
	},

	before_save(frm) {
    	let total = 0;
        let items = frm.doc.sales_contribution;
        for (let i = 0; i < items.length; i++) {
            total += items[i].allocated_percentage;
        }
        frm.set_value("total_contribution",total);
    }
});
