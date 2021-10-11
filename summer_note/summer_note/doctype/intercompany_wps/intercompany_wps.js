// Copyright (c) 2021, QCS and contributors
// For license information, please see license.txt

frappe.ui.form.on('Intercompany Wps', {
	// refresh: function(frm) {

	// }
});



frappe.ui.form.on("Intercompany Wps", {
	refresh: function(frm) {
		frm.disable_save();
	},

	create_jv: function(frm) {
		frappe.call({
			method:"summer_note.common.inter_company",
			args:{
				start_date:frm.doc.from_date,
				end_date: frm.doc.to_date

			}
		});
	}

	

});