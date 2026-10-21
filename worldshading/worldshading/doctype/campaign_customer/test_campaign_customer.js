const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const scriptPath = path.join(__dirname, "campaign_customer.js");
assert.ok(fs.existsSync(scriptPath), "Missing Campaign Customer form script");

let handlers;
let lastRead;
const responses = {
    Customer: {
        customer_name: "Acme Trading",
        customer_group: "Commercial",
        territory: "Bahrain",
        mobile_no: "39000000",
        email_id: "customer@example.com"
    },
    Contact: {
        mobile_no: "39111111",
        phone: "17000000",
        email_id: "contact@example.com"
    }
};

const sandbox = {
    frappe: {
        ui: {
            form: {
                on: function(doctype, registeredHandlers) {
                    assert.strictEqual(doctype, "Campaign Customer");
                    handlers = registeredHandlers;
                }
            }
        },
        db: {
            get_value: function(doctype, name, fields, callback) {
                lastRead = {doctype: doctype, name: name, fields: fields};
                callback({message: responses[doctype]});
            }
        }
    }
};

vm.runInNewContext(fs.readFileSync(scriptPath, "utf8"), sandbox, {
    filename: scriptPath
});

function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

assert.ok(handlers.setup, "setup handler is required");
assert.ok(handlers.customer, "customer handler is required");
assert.ok(handlers.contact_person, "contact_person handler is required");

function makeForm(values) {
    const form = {
        doc: Object.assign({}, values),
        queries: {},
        set_query: function(fieldname, query) {
            this.queries[fieldname] = query;
        },
        set_value: function(fieldname, value) {
            this.doc[fieldname] = value;
            return Promise.resolve();
        }
    };
    return form;
}

const queryForm = makeForm({customer: "CUST-0001"});
handlers.setup(queryForm);
assert.deepStrictEqual(plain(queryForm.queries.contact_person()), {
    query: "frappe.contacts.doctype.contact.contact.contact_query",
    filters: {
        link_doctype: "Customer",
        link_name: "CUST-0001"
    }
});

const customerForm = makeForm({
    customer: "CUST-0001",
    contact_person: "OLD-CONTACT",
    mobile_number: "39999999",
    email_address: ""
});
handlers.customer(customerForm);
assert.deepStrictEqual(plain(lastRead), {
    doctype: "Customer",
    name: "CUST-0001",
    fields: ["customer_name", "customer_group", "territory", "mobile_no", "email_id"]
});
assert.strictEqual(customerForm.doc.contact_person, "");
assert.strictEqual(customerForm.doc.customer_name, "Acme Trading");
assert.strictEqual(customerForm.doc.customer_group, "Commercial");
assert.strictEqual(customerForm.doc.territory, "Bahrain");
assert.strictEqual(customerForm.doc.mobile_number, "39999999");
assert.strictEqual(customerForm.doc.email_address, "customer@example.com");

const switchedCustomerForm = makeForm({
    customer: "CUST-0001",
    contact_person: "",
    mobile_number: "",
    email_address: ""
});
handlers.customer(switchedCustomerForm);
assert.strictEqual(switchedCustomerForm.doc.mobile_number, "39000000");
assert.strictEqual(switchedCustomerForm.doc.email_address, "customer@example.com");
responses.Customer.mobile_no = "39222222";
responses.Customer.email_id = "second@example.com";
switchedCustomerForm.doc.customer = "CUST-0002";
handlers.customer(switchedCustomerForm);
assert.strictEqual(switchedCustomerForm.doc.mobile_number, "39222222");
assert.strictEqual(switchedCustomerForm.doc.email_address, "second@example.com");

switchedCustomerForm.doc.mobile_number = "manual-number";
responses.Customer.mobile_no = "39333333";
responses.Customer.email_id = "third@example.com";
switchedCustomerForm.doc.customer = "CUST-0003";
handlers.customer(switchedCustomerForm);
assert.strictEqual(switchedCustomerForm.doc.mobile_number, "manual-number");
assert.strictEqual(switchedCustomerForm.doc.email_address, "third@example.com");

const contactForm = makeForm({
    contact_person: "CONTACT-0001",
    mobile_number: "39999999",
    whatsapp_number: "",
    email_address: ""
});
handlers.contact_person(contactForm);
assert.deepStrictEqual(plain(lastRead), {
    doctype: "Contact",
    name: "CONTACT-0001",
    fields: ["mobile_no", "phone", "email_id"]
});
assert.strictEqual(contactForm.doc.mobile_number, "39999999");
assert.strictEqual(contactForm.doc.whatsapp_number, "39111111");
assert.strictEqual(contactForm.doc.email_address, "contact@example.com");

const contactSwitchForm = makeForm({
    customer: "CUST-0001",
    contact_person: "CONTACT-0001",
    mobile_number: "",
    whatsapp_number: "",
    email_address: ""
});
handlers.contact_person(contactSwitchForm);
contactSwitchForm.doc.customer = "CUST-0004";
handlers.customer(contactSwitchForm);
assert.strictEqual(contactSwitchForm.doc.mobile_number, "39333333");
assert.strictEqual(contactSwitchForm.doc.whatsapp_number, "");
assert.strictEqual(contactSwitchForm.doc.email_address, "third@example.com");

responses.Contact.mobile_no = "";
const fallbackForm = makeForm({
    contact_person: "CONTACT-0002",
    mobile_number: "",
    whatsapp_number: "",
    email_address: "manual@example.com"
});
handlers.contact_person(fallbackForm);
assert.strictEqual(fallbackForm.doc.mobile_number, "17000000");
assert.strictEqual(fallbackForm.doc.whatsapp_number, "");
assert.strictEqual(fallbackForm.doc.email_address, "manual@example.com");

console.log("Campaign Customer client behavior: OK");
