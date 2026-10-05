from flask import Flask, request, jsonify, render_template_string
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

DATABASE = "lost_found.db"


# =========================================================
# DATABASE
# =========================================================

def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db


def create_database():
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_type TEXT NOT NULL,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL,
            colour TEXT,
            location TEXT NOT NULL,
            item_date TEXT NOT NULL,
            description TEXT,
            contact TEXT,
            status TEXT DEFAULT 'Active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.commit()
    db.close()


# =========================================================
# SMART MATCHING
# =========================================================

def find_matches(new_item):
    db = get_db()

    opposite_type = (
        "Found Item"
        if new_item["record_type"] == "Lost Item"
        else "Lost Item"
    )

    rows = db.execute("""
        SELECT * FROM items
        WHERE record_type = ?
        AND status = 'Active'
    """, (opposite_type,)).fetchall()

    matches = []

    for row in rows:
        score = 0

        # Category match
        if (
            row["category"].strip().lower()
            == new_item["category"].strip().lower()
        ):
            score += 35

        # Colour match
        if new_item.get("colour") and row["colour"]:
            if (
                row["colour"].strip().lower()
                == new_item["colour"].strip().lower()
            ):
                score += 20

        # Location match
        if (
            row["location"].strip().lower()
            == new_item["location"].strip().lower()
        ):
            score += 20

        # Item name similarity
        name1 = new_item["item_name"].lower()
        name2 = row["item_name"].lower()

        if name1 in name2 or name2 in name1:
            score += 25
        else:
            words1 = set(name1.split())
            words2 = set(name2.split())

            common_words = words1.intersection(words2)

            if common_words:
                score += min(len(common_words) * 10, 20)

        if score >= 40:
            matches.append({
                "id": row["id"],
                "item_name": row["item_name"],
                "record_type": row["record_type"],
                "category": row["category"],
                "colour": row["colour"],
                "location": row["location"],
                "score": score
            })

    db.close()

    matches.sort(key=lambda x: x["score"], reverse=True)

    return matches


# =========================================================
# HOME PAGE
# =========================================================

@app.route("/")
def home():
    return render_template_string(HTML)


# =========================================================
# GET ALL ITEMS
# =========================================================

@app.route("/api/items", methods=["GET"])
def get_items():

    db = get_db()

    rows = db.execute("""
        SELECT * FROM items
        ORDER BY id DESC
    """).fetchall()

    db.close()

    return jsonify([dict(row) for row in rows])


# =========================================================
# CREATE ITEM
# =========================================================

@app.route("/api/items", methods=["POST"])
def create_item():

    data = request.get_json()

    if not data:
        return jsonify({
            "success": False,
            "message": "No data received"
        }), 400

    required = [
        "record_type",
        "item_name",
        "category",
        "location",
        "item_date"
    ]

    for field in required:
        if not data.get(field):
            return jsonify({
                "success": False,
                "message": f"{field} is required"
            }), 400

    db = get_db()

    cursor = db.execute("""
        INSERT INTO items
        (
            record_type,
            item_name,
            category,
            colour,
            location,
            item_date,
            description,
            contact,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Active')
    """, (
        data["record_type"],
        data["item_name"],
        data["category"],
        data.get("colour", ""),
        data["location"],
        data["item_date"],
        data.get("description", ""),
        data.get("contact", "")
    ))

    item_id = cursor.lastrowid

    db.commit()

    row = db.execute(
        "SELECT * FROM items WHERE id = ?",
        (item_id,)
    ).fetchone()

    db.close()

    item = dict(row)

    matches = find_matches(item)

    return jsonify({
        "success": True,
        "message": "Item saved successfully",
        "item": item,
        "matches": matches
    })


# =========================================================
# GET SINGLE ITEM
# =========================================================

@app.route("/api/items/<int:item_id>", methods=["GET"])
def get_item(item_id):

    db = get_db()

    row = db.execute(
        "SELECT * FROM items WHERE id = ?",
        (item_id,)
    ).fetchone()

    db.close()

    if not row:
        return jsonify({
            "success": False,
            "message": "Item not found"
        }), 404

    return jsonify(dict(row))


# =========================================================
# UPDATE ITEM
# =========================================================

@app.route("/api/items/<int:item_id>", methods=["PUT"])
def update_item(item_id):

    data = request.get_json()

    db = get_db()

    existing = db.execute(
        "SELECT * FROM items WHERE id = ?",
        (item_id,)
    ).fetchone()

    if not existing:
        db.close()

        return jsonify({
            "success": False,
            "message": "Item not found"
        }), 404

    db.execute("""
        UPDATE items
        SET
            record_type = ?,
            item_name = ?,
            category = ?,
            colour = ?,
            location = ?,
            item_date = ?,
            description = ?,
            contact = ?
        WHERE id = ?
    """, (
        data["record_type"],
        data["item_name"],
        data["category"],
        data.get("colour", ""),
        data["location"],
        data["item_date"],
        data.get("description", ""),
        data.get("contact", ""),
        item_id
    ))

    db.commit()

    row = db.execute(
        "SELECT * FROM items WHERE id = ?",
        (item_id,)
    ).fetchone()

    db.close()

    return jsonify({
        "success": True,
        "message": "Item updated successfully",
        "item": dict(row)
    })


# =========================================================
# DELETE ITEM
# =========================================================

@app.route("/api/items/<int:item_id>", methods=["DELETE"])
def delete_item(item_id):

    db = get_db()

    cursor = db.execute(
        "DELETE FROM items WHERE id = ?",
        (item_id,)
    )

    db.commit()

    deleted = cursor.rowcount

    db.close()

    if deleted == 0:
        return jsonify({
            "success": False,
            "message": "Item not found"
        }), 404

    return jsonify({
        "success": True,
        "message": "Item deleted successfully"
    })


# =========================================================
# MARK ITEM AS RESOLVED
# =========================================================

@app.route("/api/items/<int:item_id>/resolve", methods=["PUT"])
def resolve_item(item_id):

    db = get_db()

    db.execute("""
        UPDATE items
        SET status = 'Resolved'
        WHERE id = ?
    """, (item_id,))

    db.commit()
    db.close()

    return jsonify({
        "success": True,
        "message": "Item marked as resolved"
    })


# =========================================================
# MATCHES
# =========================================================

@app.route("/api/matches/<int:item_id>", methods=["GET"])
def get_matches(item_id):

    db = get_db()

    row = db.execute(
        "SELECT * FROM items WHERE id = ?",
        (item_id,)
    ).fetchone()

    db.close()

    if not row:
        return jsonify([])

    matches = find_matches(dict(row))

    return jsonify(matches)


# =========================================================
# FRONTEND
# =========================================================

HTML = r"""
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>FINDLY | Smart Lost & Found</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: Arial, Helvetica, sans-serif;
    background: #f4f7fb;
    color: #172033;
}

header {
    background: white;
    border-bottom: 1px solid #e3e8ef;
    padding: 18px 7%;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.logo {
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 23px;
    font-weight: 800;
    color: #243b64;
}

.logo-icon {
    width: 38px;
    height: 38px;
    border-radius: 10px;
    background: #2f6fed;
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
}

.header-text {
    color: #718096;
    font-size: 13px;
}

.container {
    width: 86%;
    max-width: 1250px;
    margin: 35px auto;
}

.hero {
    margin-bottom: 25px;
}

.hero h1 {
    margin: 0;
    font-size: 34px;
    color: #172b4d;
}

.hero p {
    color: #718096;
    margin-top: 8px;
}

.stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 25px;
}

.stat {
    background: white;
    padding: 20px;
    border: 1px solid #e5eaf1;
    border-radius: 12px;
}

.stat-title {
    color: #718096;
    font-size: 12px;
    text-transform: uppercase;
}

.stat-value {
    font-size: 28px;
    font-weight: 700;
    margin-top: 8px;
    color: #20395f;
}

.card {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 28px;
    margin-bottom: 25px;
}

.card h2 {
    margin-top: 0;
    color: #233b61;
}

.subtitle {
    color: #718096;
    font-size: 14px;
    margin-bottom: 24px;
}

.form-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 18px;
}

.field {
    display: flex;
    flex-direction: column;
}

.field.full {
    grid-column: 1 / -1;
}

label {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 7px;
    color: #344563;
}

input,
select,
textarea {
    width: 100%;
    padding: 12px 13px;
    border: 1px solid #d7dee8;
    border-radius: 8px;
    font-size: 14px;
    background: white;
    outline: none;
}

input:focus,
select:focus,
textarea:focus {
    border-color: #2f6fed;
}

textarea {
    min-height: 90px;
    resize: vertical;
}

.form-actions {
    margin-top: 22px;
    display: flex;
    gap: 10px;
}

button {
    border: none;
    cursor: pointer;
    border-radius: 8px;
    padding: 11px 18px;
    font-weight: 600;
}

.primary {
    background: #2f6fed;
    color: white;
}

.primary:hover {
    background: #245dcc;
}

.secondary {
    background: #edf1f6;
    color: #344563;
}

.danger {
    background: #fff0f0;
    color: #c53030;
}

.resolve {
    background: #edf8f1;
    color: #287d48;
}

.table-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 15px;
    margin-bottom: 18px;
}

.search {
    max-width: 280px;
}

.table-wrapper {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
}

th {
    text-align: left;
    padding: 13px;
    background: #f7f9fc;
    color: #667085;
    font-size: 12px;
    text-transform: uppercase;
}

td {
    padding: 14px 13px;
    border-top: 1px solid #edf0f4;
    font-size: 13px;
}

.badge {
    display: inline-block;
    padding: 5px 9px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
}

.badge-lost {
    background: #fff4e5;
    color: #a85d00;
}

.badge-found {
    background: #edf8f1;
    color: #287d48;
}

.badge-resolved {
    background: #eef1f5;
    color: #667085;
}

.actions {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
}

.empty {
    text-align: center;
    padding: 45px;
    color: #8a94a6;
}

.match-box {
    background: #f7f9fc;
    border-left: 4px solid #2f6fed;
    padding: 16px;
    margin-top: 20px;
    border-radius: 8px;
    display: none;
}

.match-item {
    background: white;
    padding: 12px;
    margin-top: 8px;
    border: 1px solid #e3e8ef;
    border-radius: 7px;
}

.toast {
    position: fixed;
    right: 25px;
    bottom: 25px;
    background: #172b4d;
    color: white;
    padding: 13px 18px;
    border-radius: 8px;
    display: none;
    z-index: 999;
}

@media(max-width: 800px) {

    .stats {
        grid-template-columns: 1fr 1fr;
    }

    .form-grid {
        grid-template-columns: 1fr;
    }

    .field.full {
        grid-column: auto;
    }

    .table-header {
        flex-direction: column;
        align-items: stretch;
    }

    .search {
        max-width: none;
    }

}

</style>

</head>


<body>


<header>

    <div class="logo">
        <div class="logo-icon">●</div>
        FINDLY
    </div>

    <div class="header-text">
        Smart Lost & Found Management System
    </div>

</header>


<div class="container">


    <div class="hero">

        <h1>Smart Lost & Found</h1>

        <p>
            Report, manage and identify possible matches
            for lost and found items.
        </p>

    </div>


    <!-- STATISTICS -->

    <div class="stats">

        <div class="stat">
            <div class="stat-title">Total Records</div>
            <div class="stat-value" id="totalRecords">0</div>
        </div>

        <div class="stat">
            <div class="stat-title">Lost Items</div>
            <div class="stat-value" id="lostItems">0</div>
        </div>

        <div class="stat">
            <div class="stat-title">Found Items</div>
            <div class="stat-value" id="foundItems">0</div>
        </div>

        <div class="stat">
            <div class="stat-title">Possible Matches</div>
            <div class="stat-value" id="possibleMatches">0</div>
        </div>

    </div>


    <!-- FORM -->

    <div class="card">

        <h2 id="formTitle">
            Report Lost / Found Item
        </h2>

        <div class="subtitle">
            Enter the item details below.
        </div>


        <form id="itemForm">


            <div class="form-grid">


                <div class="field">

                    <label>
                        Record Type *
                    </label>

                    <select id="record_type" required>

                        <option value="Lost Item">
                            Lost Item
                        </option>

                        <option value="Found Item">
                            Found Item
                        </option>

                    </select>

                </div>


                <div class="field">

                    <label>
                        Item Name *
                    </label>

                    <input
                        id="item_name"
                        placeholder="Example: Black Wallet"
                        required
                    >

                </div>


                <div class="field">

                    <label>
                        Category *
                    </label>

                    <select id="category" required>

                        <option value="">
                            Select Category
                        </option>

                        <option>Wallet</option>
                        <option>Mobile Phone</option>
                        <option>Laptop</option>
                        <option>Bag</option>
                        <option>ID Card</option>
                        <option>Keys</option>
                        <option>Book</option>
                        <option>Earphones</option>
                        <option>Watch</option>
                        <option>Other</option>

                    </select>

                </div>


                <div class="field">

                    <label>
                        Colour
                    </label>

                    <input
                        id="colour"
                        placeholder="Example: Black"
                    >

                </div>


                <div class="field">

                    <label>
                        Location *
                    </label>

                    <input
                        id="location"
                        placeholder="Example: College Canteen"
                        required
                    >

                </div>


                <div class="field">

                    <label>
                        Date *
                    </label>

                    <input
                        id="item_date"
                        type="date"
                        required
                    >

                </div>


                <div class="field full">

                    <label>
                        Description
                    </label>

                    <textarea
                        id="description"
                        placeholder="Describe the item..."
                    ></textarea>

                </div>


                <div class="field">

                    <label>
                        Contact
                    </label>

                    <input
                        id="contact"
                        placeholder="Phone / Email"
                    >

                </div>


            </div>


            <div class="form-actions">

                <button
                    class="primary"
                    type="submit"
                    id="saveButton"
                >
                    Save Item
                </button>

                <button
                    class="secondary"
                    type="button"
                    onclick="resetForm()"
                >
                    Clear
                </button>

            </div>


        </form>


        <!-- MATCH RESULTS -->

        <div
            class="match-box"
            id="matchBox"
        >

            <strong>
                Possible Matching Items
            </strong>

            <div id="matchResults"></div>

        </div>

    </div>


    <!-- TABLE -->

    <div class="card">

        <div class="table-header">

            <div>

                <h2 style="margin-bottom:5px;">
                    Item Records
                </h2>

                <div class="subtitle"
                     style="margin:0;">
                    Manage all reported items.
                </div>

            </div>


            <input
                class="search"
                id="search"
                placeholder="Search records..."
                oninput="displayItems()"
            >

        </div>


        <div class="table-wrapper">

            <table>

                <thead>

                    <tr>

                        <th>ID</th>
                        <th>Type</th>
                        <th>Item</th>
                        <th>Category</th>
                        <th>Colour</th>
                        <th>Location</th>
                        <th>Date</th>
                        <th>Status</th>
                        <th>Actions</th>

                    </tr>

                </thead>


                <tbody id="itemTable">

                </tbody>

            </table>

        </div>

    </div>


</div>


<div
    class="toast"
    id="toast"
></div>


<script>


let allItems = [];

let editingId = null;


// =====================================================
// TOAST
// =====================================================

function showToast(message) {

    const toast =
        document.getElementById("toast");

    toast.innerText = message;

    toast.style.display = "block";

    setTimeout(() => {

        toast.style.display = "none";

    }, 2500);

}


// =====================================================
// LOAD ITEMS
// =====================================================

async function loadItems() {

    try {

        const response =
            await fetch("/api/items");

        allItems =
            await response.json();

        displayItems();

        updateStats();

    }

    catch(error) {

        console.error(error);

        showToast(
            "Unable to connect to server."
        );

    }

}


// =====================================================
// DISPLAY ITEMS
// =====================================================

function displayItems() {

    const table =
        document.getElementById("itemTable");

    const search =
        document
            .getElementById("search")
            .value
            .toLowerCase();


    const filtered =
        allItems.filter(item => {

            return (

                item.item_name
                    .toLowerCase()
                    .includes(search)

                ||

                item.category
                    .toLowerCase()
                    .includes(search)

                ||

                item.location
                    .toLowerCase()
                    .includes(search)

                ||

                item.record_type
                    .toLowerCase()
                    .includes(search)

            );

        });


    if(filtered.length === 0) {

        table.innerHTML = `
            <tr>
                <td colspan="9" class="empty">
                    No records found.
                </td>
            </tr>
        `;

        return;

    }


    table.innerHTML =
        filtered.map(item => `

        <tr>

            <td>${item.id}</td>

            <td>
                <span class="badge ${
                    item.record_type === "Lost Item"
                    ? "badge-lost"
                    : "badge-found"
                }">
                    ${item.record_type}
                </span>
            </td>

            <td>
                <strong>
                    ${escapeHtml(item.item_name)}
                </strong>
            </td>

            <td>
                ${escapeHtml(item.category)}
            </td>

            <td>
                ${escapeHtml(item.colour || "-")}
            </td>

            <td>
                ${escapeHtml(item.location)}
            </td>

            <td>
                ${escapeHtml(item.item_date)}
            </td>

            <td>

                <span class="badge ${
                    item.status === "Resolved"
                    ? "badge-resolved"
                    : "badge-found"
                }">

                    ${item.status}

                </span>

            </td>

            <td>

                <div class="actions">

                    <button
                        class="secondary"
                        onclick="viewItem(${item.id})"
                    >
                        View
                    </button>

                    <button
                        class="primary"
                        onclick="editItem(${item.id})"
                    >
                        Edit
                    </button>

                    ${
                        item.status === "Active"
                        ?
                        `
                        <button
                            class="resolve"
                            onclick="resolveItem(${item.id})"
                        >
                            Resolve
                        </button>
                        `
                        :
                        ""
                    }

                    <button
                        class="danger"
                        onclick="deleteItem(${item.id})"
                    >
                        Delete
                    </button>

                </div>

            </td>

        </tr>

    `).join("");

}


// =====================================================
// SAVE / UPDATE
// =====================================================

document
    .getElementById("itemForm")
    .addEventListener("submit", async function(event) {

        event.preventDefault();


        const data = {

            record_type:
                document
                .getElementById("record_type")
                .value,

            item_name:
                document
                .getElementById("item_name")
                .value.trim(),

            category:
                document
                .getElementById("category")
                .value,

            colour:
                document
                .getElementById("colour")
                .value.trim(),

            location:
                document
                .getElementById("location")
                .value.trim(),

            item_date:
                document
                .getElementById("item_date")
                .value,

            description:
                document
                .getElementById("description")
                .value.trim(),

            contact:
                document
                .getElementById("contact")
                .value.trim()

        };


        try {


            let response;


            // UPDATE
            if(editingId) {

                response =
                    await fetch(
                        `/api/items/${editingId}`,
                        {

                            method: "PUT",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body:
                                JSON.stringify(data)

                        }
                    );

            }


            // CREATE
            else {

                response =
                    await fetch(
                        "/api/items",
                        {

                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body:
                                JSON.stringify(data)

                        }
                    );

            }


            const result =
                await response.json();


            if(!response.ok) {

                throw new Error(
                    result.message ||
                    "Operation failed"
                );

            }


            if(editingId) {

                showToast(
                    "Item updated successfully."
                );

            }

            else {

                showToast(
                    "Item saved successfully."
                );

                if(result.matches &&
                   result.matches.length > 0) {

                    showMatches(
                        result.matches
                    );

                }

            }


            editingId = null;

            document
                .getElementById("saveButton")
                .innerText = "Save Item";


            resetForm(false);

            await loadItems();

        }


        catch(error) {

            console.error(error);

            showToast(
                error.message
            );

        }

    });


// =====================================================
// VIEW
// =====================================================

async function viewItem(id) {

    const response =
        await fetch(`/api/items/${id}`);

    const item =
        await response.json();


    alert(

        "ITEM DETAILS\n\n" +

        "Type: " +
        item.record_type + "\n" +

        "Item: " +
        item.item_name + "\n" +

        "Category: " +
        item.category + "\n" +

        "Colour: " +
        (item.colour || "-") + "\n" +

        "Location: " +
        item.location + "\n" +

        "Date: " +
        item.item_date + "\n\n" +

        "Description: " +
        (item.description || "-") + "\n\n" +

        "Contact: " +
        (item.contact || "-")

    );

}


// =====================================================
// EDIT
// =====================================================

async function editItem(id) {

    const response =
        await fetch(`/api/items/${id}`);

    const item =
        await response.json();


    editingId = id;


    document
        .getElementById("record_type")
        .value = item.record_type;

    document
        .getElementById("item_name")
        .value = item.item_name;

    document
        .getElementById("category")
        .value = item.category;

    document
        .getElementById("colour")
        .value = item.colour || "";

    document
        .getElementById("location")
        .value = item.location;

    document
        .getElementById("item_date")
        .value = item.item_date;

    document
        .getElementById("description")
        .value =
            item.description || "";

    document
        .getElementById("contact")
        .value =
            item.contact || "";


    document
        .getElementById("saveButton")
        .innerText = "Update Item";


    window.scrollTo({
        top: 0,
        behavior: "smooth"
    });

}


// =====================================================
// DELETE
// =====================================================

async function deleteItem(id) {

    if(!confirm(
        "Are you sure you want to delete this item?"
    )) {

        return;

    }


    try {

        const response =
            await fetch(
                `/api/items/${id}`,
                {
                    method: "DELETE"
                }
            );


        const result =
            await response.json();


        if(!response.ok) {

            throw new Error(
                result.message
            );

        }


        showToast(
            "Item deleted successfully."
        );


        await loadItems();

    }


    catch(error) {

        showToast(
            error.message
        );

    }

}


// =====================================================
// RESOLVE
// =====================================================

async function resolveItem(id) {

    try {

        await fetch(
            `/api/items/${id}/resolve`,
            {
                method: "PUT"
            }
        );


        showToast(
            "Item marked as resolved."
        );


        await loadItems();

    }

    catch(error) {

        showToast(
            "Unable to update item."
        );

    }

}


// =====================================================
// MATCHES
// =====================================================

function showMatches(matches) {

    const box =
        document.getElementById("matchBox");

    const results =
        document.getElementById("matchResults");


    box.style.display = "block";


    if(matches.length === 0) {

        results.innerHTML =
            "<p>No possible matches found.</p>";

        return;

    }


    results.innerHTML =
        matches.map(match => `

            <div class="match-item">

                <strong>
                    ${escapeHtml(match.item_name)}
                </strong>

                <br>

                <small>
                    ${match.record_type}
                    ·
                    ${match.category}
                    ·
                    ${match.location}
                </small>

                <br>

                <small>
                    Match Score:
                    <strong>
                        ${match.score}%
                    </strong>
                </small>

            </div>

        `).join("");

}


// =====================================================
// RESET FORM
// =====================================================

function resetForm(clearMatch = true) {

    document
        .getElementById("itemForm")
        .reset();


    editingId = null;


    document
        .getElementById("saveButton")
        .innerText = "Save Item";


    if(clearMatch) {

        document
            .getElementById("matchBox")
            .style.display = "none";

    }

}


// =====================================================
// STATISTICS
// =====================================================

function updateStats() {

    document
        .getElementById("totalRecords")
        .innerText =
            allItems.length;


    document
        .getElementById("lostItems")
        .innerText =
            allItems.filter(
                x => x.record_type === "Lost Item"
            ).length;


    document
        .getElementById("foundItems")
        .innerText =
            allItems.filter(
                x => x.record_type === "Found Item"
            ).length;


    let matches = 0;

    for(let item of allItems) {

        const opposite =
            item.record_type === "Lost Item"
            ? "Found Item"
            : "Lost Item";


        const possible =
            allItems.filter(other =>

                other.id !== item.id &&

                other.record_type === opposite &&

                other.status === "Active" &&

                other.category.toLowerCase()
                === item.category.toLowerCase()

            );


        if(possible.length > 0) {

            matches++;

        }

    }


    document
        .getElementById("possibleMatches")
        .innerText = matches;

}


// =====================================================
// HTML ESCAPE
// =====================================================

function escapeHtml(value) {

    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");

}


// =====================================================
// START
// =====================================================

document
    .getElementById("item_date")
    .value =
        new Date()
        .toISOString()
        .split("T")[0];


loadItems();

</script>


</body>

</html>
"""


# =========================================================
# START APPLICATION
# =========================================================

if __name__ == "__main__":

    create_database()

    print()
    print("-------------------------------------------")
    print(" FINDLY - SMART LOST & FOUND")
    print("-------------------------------------------")
    print(" Open: http://127.0.0.1:5000")
    print("-------------------------------------------")
    print()

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False,
        use_reloader=False
    )