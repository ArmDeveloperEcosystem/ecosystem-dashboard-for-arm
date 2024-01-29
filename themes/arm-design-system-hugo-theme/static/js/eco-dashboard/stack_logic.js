function unpinAll() {
    // iterate over all row elements to unpin...
    var currently_pinned_rows = document.getElementById('sw-tablebody').querySelectorAll('tr.main-sw-row.js-pinned');
    for (const row of currently_pinned_rows) {
        unpinRow(row);
    }
}


function pinTheseRows(pin_array_sanitized) {

    // iterate over array
    for (const name_to_pin of pin_array_sanitized) {
        var row_to_pin = document.querySelector('[data-name="'+name_to_pin+'"]'); 
        if (row_to_pin) {
            pinRow(row_to_pin);
        }
        else {
            console.log('Could not identify this package to pin, check your name and try again: ',name_to_pin);
        }
    }
}


function updateStackRow(stack_card) {
    // Update text with stack.md card, obtained dynamically.
    var stack_row = document.getElementById('stack-info-row');
    var title_area = document.getElementById('stack-title');
    var description_area = document.getElementById('stack-description');
    var image_area = document.getElementById('stack-image');

    var title = stack_card.getAttribute('data-title');
    if (title) {
        title_area.textContent = title;
    }

    var description = stack_card.getAttribute('data-long-description');
    if (description) {
        description_area.textContent = description;
    }

    var image = stack_card.getAttribute('data-image');
    if (image) {
        image_area.textContent = image;
    }

    // show stack row
    stack_row.removeAttribute('hidden');
}

function stackClickHandler(stack_card) {
    // 1) If any rows are already pinned, open modal to ask permission to do this first.
    if (document.getElementsByClassName('js-pinned').length !== 0) {
        //document.getElementById('table-update-modal').open();
    }

    // 2) Unpin all software to reset order and clear existing pins.
    unpinAll();

    // 3) Pin rows that are selected.
    pinTheseRows(stack_card.getAttribute('data-sw-included').split(','));

    // 4) Modify and show stack info row.
    updateStackRow(stack_card);
}
function proceedWithTableUpdate() {
    console.log('need to convert this into a call back.')
}

