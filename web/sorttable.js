
var howSorted = -2;          // Starts out sorted by Site Name Ascending

function extractkey (text, is_number) {
    // A function for getting the comparison key from the cell contents

    var output = text;

    if (is_number) {
        if (output.indexOf('href') > 0) {
            output = output.split('>')[1].split('<')[0];
        }
        output = Number(output.split(' ')[0]);
    }

    return output;

}

function sorttable (column, is_number = true) {

    if (Math.abs(column) == Math.abs(howSorted)) {
        howSorted *= -1;
    } else {
        howSorted = column;
    }

    column = Math.abs(column);

    // Sort by insertion
    var table = document.getElementById('consistency_summary');

    var num_rows = table.rows.length;
    for (var i_row = 1; i_row < num_rows; i_row++) {

        // Track index to place
        var to_place = i_row;
        var row = table.rows[i_row];

        // Get the cell we want
        var cell = extractkey(row.cells[column - 1].innerHTML, is_number);

        // Compare until we find where to insert
        for (var prev = i_row - 1; prev > 0; prev -= 1) {
            var compare = extractkey(table.rows[prev].cells[column - 1].innerHTML, is_number);

            if (cell != compare && ((cell > compare) == (howSorted > 0))) {
                to_place -= 1;
            } else {
                break;
            }
        }

        if (to_place != i_row) {
            // Insert new row
            table.insertRow(to_place).innerHTML = row.innerHTML;
            // Remove old row
            table.deleteRow(i_row + 1);
        }
    }
}
