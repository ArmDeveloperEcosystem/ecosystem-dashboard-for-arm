function showAdditionalData(row) {
    var newRow = document.createElement("tr");
    newRow.innerHTML = `
        <td class='expanded-container' colspan="3">
            <div class="sw-information-grid">
                <section class="u-flex sw-information">
                    <div class="field">Description</div>
                    <div class="description">from hugo async</div>
                </section>
            </div>
        </td>
    `;
    row.parentNode.insertBefore(newRow, row.nextSibling);
}


function rowClickHandler(row) {

    // Already highlighted
    if (row.classList.contains("main-sw-row--clicked")) {
        // remove highlighting
        row.classList.remove("main-sw-row--clicked");
        // hide sub-DOM
        
        row.nextElementSibling.setAttribute('hidden',true);

    } 
    // Not highlighted
    else {
        // add highlighting
        row.classList.add("main-sw-row--clicked");
        // show DOM
        row.nextElementSibling.removeAttribute('hidden');
        // showAdditionalData(row) // needed when async grabbing data in round two. 
    }

}




function pinRow(row) {
    // If row is already pinned, exit now. Need for 'stack' functionality
    if (row.classList.contains('js-pinned')) {  return  }


    // obtain other nodes around row
    var subrow = row.nextElementSibling;
    var pin = row.querySelector('.fa-thumbtack')
    var table_body = row.closest('tbody'); // The parent node of the row
    var first_unpinned_row = table_body.querySelector('tr:not(.js-pinned)');




    // clone row/subrow inplace with a 'placeholder' class to hide them, to keep place in order.
    var row_placeholder = row.cloneNode(true);
    row_placeholder.setAttribute("id", row.getAttribute("id")+"-placeholder");   // Append "-placeholder" to the id to enable back-linking of pinned row to this placeholder
    row_placeholder.setAttribute('hidden',true);                                        // class to hide the row
    row.parentNode.insertBefore(row_placeholder, row.nextSibling);                      // Place cloned placeholder row right next to its sibling in place!    

    var subrow_placeholder = subrow.cloneNode(true);
    subrow_placeholder.setAttribute("id", subrow.getAttribute("id")+"-placeholder"); // Append "-placeholder" to the id to enable back-linking of pinned row to this placeholder
    subrow_placeholder.setAttribute('hidden',true);                                         // class to hide the row
    subrow.parentNode.insertBefore(subrow_placeholder, subrow.nextSibling);        


    // straighten pin
    pin.classList.remove("rotated");
    
    // Add class to row indicating it is pinned
    row.classList.add("main-sw-row--pinned");    // for CSS behavior
    row.classList.add("js-pinned");              // for JS behavior
    subrow.classList.add("js-pinned");           // for JS behavior
    // remove hidden attribute
    row.removeAttribute('hidden',true);    


    // move 'row_of_pin' to top of table when pinned
    if (first_unpinned_row) {
        table_body.insertBefore(row, first_unpinned_row);
        table_body.insertBefore(subrow, row.nextSibling); // Insert subrow just below the main row
    }
}


function unpinRow(row) {
    // obtain other nodes around row
    var subrow = row.nextElementSibling;
    var pin = row.querySelector('.fa-thumbtack')
    var table_body = row.closest('tbody'); // The parent node of the row
    var first_unpinned_row = table_body.querySelector('tr:not(.js-pinned)');


    // Re-Rotate pin
    pin.classList.add("rotated");

    // Remove 3 classes to row indicating it is not pinned:
        // 1. the css styling class
        // 2. the js affecting class for main-sw-row
        // 2. the js affecting class for sub-sw-row
    row.classList.remove("main-sw-row--pinned");
    row.classList.remove("js-pinned");
    subrow.classList.remove("js-pinned");            

    // Gather variables from rows before removing them.
    var pinned_id     = row.getAttribute("id");        // ID, for an ID swap
    var pinned_closed = subrow.getAttribute("hidden")  // if closed (true if closed, null if open)...carry trait to placeholder

    // Delete pinned row after getting their IDs to avoid interferance.
    row.remove();
    subrow.remove();

    // Obtain placeholder rows by pinned rows IDs
    var row_placeholder = document.getElementById(pinned_id+'-placeholder');    // match id to placeholder row  
    var subrow_placeholder = document.getElementById('sub'+pinned_id+'-placeholder');          // get subrow                       // get placeholder subrow

    // Set IDs ==== Update 'placeholder' rows to 'real' rows via ID swap
    row_placeholder.setAttribute("id", row_placeholder.getAttribute("id").replace("-placeholder",''));   // Remove '-placeholder' from ID
    subrow_placeholder.setAttribute("id", subrow_placeholder.getAttribute("id").replace("-placeholder",''));

    // UNSELECT === Always remove 'main-sw-row--clicked' when unpinned (if open, next step will add back)
    row_placeholder.classList.remove("main-sw-row--clicked");


    // Set OPEN === If subrow is open, carry over trait
        // DONT DO THIS NOW. Causes more trouble than it's worth....implement later once cleaned logic.

    // Re-run any active search, as it needs to update (should unpinned row still show or not?)
    document.getElementById('search-box').value().then((value) => {              // Get search query (inside promise, continue the rest of this inside the promise)
        let current_search = value;
        if (current_search) {
            // Have search deterimine if row should be shown or not.
            searchHandler(current_search);
        }
        else {
            // If no search, need to manually unhide row as it should always display.
            row_placeholder.removeAttribute('hidden');
        }
    });

}




function pinClickHandler(event) {
    event.stopPropagation(); /* stop clicking of row underneath thumbtack */
    var pin = event.target;
    var row_of_pin = pin.closest('tr');
    var subrow_of_pin = row_of_pin.nextElementSibling;
    var table_body = row_of_pin.closest('tbody') || row_of_pin.closest('table'); // The parent node of the row
    var first_unpinned_row = table_body.querySelector('tr:not(.js-pinned)');

    // Already selected, unpin
    if (!pin.classList.contains("rotated")) {
        unpinRow(row_of_pin);
    } 
    // Not selected, pin
    else {
        pinRow(row_of_pin);
    }

    // Hide stack row always, as it interfears with the stack info.
    document.getElementById('stack-info-row').setAttribute('hidden',true);
}
