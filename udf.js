/**
 * Safe CSV parser that respects quoted fields and escaped quotes
 */
function parseCSV(line) {
  if (!line || typeof line !== "string") {
    return [];
  }

  var result = [];
  var current = "";
  var inQuotes = false;

  for (var i = 0; i < line.length; i++) {
    var char = line[i];

    if (char === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === "," && !inQuotes) {
      result.push(current);
      current = "";
    } else {
      current += char;
    }
  }

  result.push(current);
  return result;
}

/**
 * Safe integer parsing
 */
function safeParseInt(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  var parsed = parseInt(value, 10);
  return isNaN(parsed) ? null : parsed;
}

/**
 * Validate YYYY-MM-DD format
 */
function isValidDate(dateStr) {
  if (!dateStr || typeof dateStr !== "string") {
    return false;
  }

  var regex = /^\d{4}-\d{2}-\d{2}$/;
  return regex.test(dateStr);
}

function transform(line) {

  // Reject null/empty lines
  if (!line || typeof line !== "string" || line.trim() === "") {
    return null;
  }

  var values = parseCSV(line);

  // Skip header safely
  if (values.length > 0 && values[0] === "EmployeeID") {
    return null;
  }

  // Minimum column validation (expecting 9 columns)
  if (values.length < 9) {
    return null; // malformed row
  }

  var obj = {};

  // -------------------------
  // Core Fields
  // -------------------------

  obj.EmployeeID = safeParseInt(values[0]);

  obj.FirstName = values[1] ? values[1].trim() : null;
  obj.LastName = values[2] ? values[2].trim() : null;
  obj.Department = values[3] ? values[3].trim() : null;
  obj.Position = values[4] ? values[4].trim() : null;

  obj.Salary = safeParseInt(values[5]);

  var joiningDate = values[6] ? values[6].trim() : null;
  obj.JoiningDate = isValidDate(joiningDate) ? joiningDate : null;

  // Country exists in CSV but not in BQ schema
  var country = values[7] ? values[7].trim() : null;

  // -------------------------
  // Tag Fields (Dynamic)
  // -------------------------

  obj.CMDB_APP_ID = null;
  obj.COST_CENTRE = null;
  obj.Environment = null;

  var tagsColumn = values[8];

  if (tagsColumn && typeof tagsColumn === "string") {
    try {

      var tags = JSON.parse(tagsColumn);

      if (Array.isArray(tags)) {
        for (var i = 0; i < tags.length; i++) {

          if (!tags[i] || !tags[i].key) {
            continue;
          }

          var key = String(tags[i].key).toLowerCase();
          var value = tags[i].value ? String(tags[i].value).trim() : null;

          if (key === "cmdb_app_id") {
            obj.CMDB_APP_ID = value;
          } else if (key === "cost_centre") {
            obj.COST_CENTRE = value;
          } else if (key === "environment") {
            obj.Environment = value;
          }
        }
      }

    } catch (e) {
      // Invalid JSON → leave tag fields null
    }
  }

  // -------------------------
  // Final Defensive Validation
  // -------------------------

  // Reject row if mandatory fields are missing
  if (obj.EmployeeID === null) {
    return null;
  }

  return JSON.stringify(obj);
}