

/* Used to replace the default loaded screen (just a few most recent packages displayed) with the larger packages table. */
function setToBrowse() {

    var main_table_div = document.getElementById('all-packages-div');

    // quickly return if browse already activated
    if (main_table_div.getAttribute('browse'))
        { return }
   
    // Hide dashboard information
    document.getElementById('initial-dashboard-display').classList.add('hidden');

    // Show all package table
    main_table_div.classList.remove('hidden');

    // Update shown number of packages
    updateShownNumber();

    // Set browse 'True' attribute to 
    main_table_div.setAttribute('browse',true);
}

/* Sanatizes html browser (and a few other) inputs to avoid injection and html errors */
function sanitizeInput(potentially_unsafe_str) {
    // Sanitize the input by only allowing the following characters through, replacing all others with nothing:
        // a-z
        // A-Z
        // 0-9 digits
        // special characters: .-=
            // - very common in code
            // = needed for param filtering to work easily
    let sanitized_str = potentially_unsafe_str.replaceAll(/[^a-z A-Z 0-9 .=-]+/g, "");
    return sanitized_str
}


function URLsearchAndfiltering(url_str) {
    // Prep params using built in JS functions
    const params = new URLSearchParams(url_str);

    // get Search string
    const search_string = sanitizeInput(params.get('search') || '');

    // get filters to activate
        // TO DO
    
    // Activate searching & filtering.
        // Call search handler to execute search
        if (search_string) {
            search_box.setAttribute('search-value',search_string);
            searchHandler(search_string);
        }
        // TO DO ADD FILTER HANDELER!

}

/* Hides (and shows) table elements by modifying the row's hidden attribute */
function hideElements(all_path_cards,results_to_hide) {
    // Hide elements in array (and actively show all OTHER elements)
    for (let card of all_path_cards) {
        if (results_to_hide.includes(card)) { 
            // Hide card and subrow!
            card.setAttribute('hidden',true);
            // Remove 'clicked' attribute
            card.classList.remove("main-sw-row--clicked");

            if (card.nextElementSibling){   // temp to enable card view too
                card.nextElementSibling.setAttribute('hidden',true);
            }
        }
        else {
            // Show card, if it is NOT a placeholder (those obviously stay hidden).
            if (!card.getAttribute("id").includes('-placeholder')) {
                card.removeAttribute('hidden');
            }
        }
    }
}

/* Updates the UI to indicate the correct # of packages currently displayed */
function updateShownNumber() {

    // Update UI telling how many are displayed
    let current_num = document.getElementById('currently-shown-number').innerHTML;
    let total_num = document.getElementById('total-shown-number').innerHTML;
    var hidden_paths = document.querySelectorAll('.search-div[hidden]:not([hidden=""])');

    // adjust string length when open filter (not sure why needed currently)
    let paths_hidden = hidden_paths.length;

    document.getElementById('currently-shown-number').innerHTML = parseInt(total_num) - paths_hidden;
}

/* Only for pins....could delete */
function searchKeepPinnedrow(card) {
    // if card is pinned, return false to show it. Else, return true to hide it.

    // how to tell if card is pinned? has class 'js-pinned
    if (card.classList.contains('js-pinned')) {
        return false
    }
    else {
        return true
    }
    
}


/* Logic to determine if a row should be hidden based on active filters */
function filter_card(card) {
    let to_hide = true;             // set as true by default; change to false if conditions apply

    // iterate over all active filters in the dom area; if this card matches ALL of the tags, keep shown
    const active_tags = document.getElementsByClassName('filter-facet');
    if (active_tags.length==0) { return false }        // Return already if no tags...no filtering neccecary 

    for (let tag of active_tags) {
        let filter_facet_html = tag.textContent.trim();
        // Category: AI/ML -->  tag-category-ai-ml  let pass all cards that have 'tag-category-ai-ml' as part of className.
        // License: All    -->  tag-license         let pass all cards that have 'tag-license-' as part of className.
        let filter_facet_sanitized = filter_facet_html.replace('/','__').toLowerCase()      // license: open source         category: ai__ml
        let filter_facet_organized = filter_facet_sanitized.replace(': ','-');              // license-open source          category-ai__ml
        //let active_tag_name = 'tag-'+filter_facet_organized.replaceAll(' ','-');               // tag-license-open-source      tag-category-ai__ml
        
        // Very complex regex expression to simply always replace ' ' with dashes, EXCEPT when preceeding or following dashes (such as in a category like 'Databases - big-data'
        let active_tag_name = 'tag-' + filter_facet_organized.replace(/(\s+)(?=-)|(?<=-)(\s+)/g, '').replaceAll(/\s/g, '-');

        if ((active_tag_name.endsWith('-all')) || (card.classList.contains(active_tag_name))) {
            // Card is not proven to be hidden; continue through the other filter groups.
            continue
        }
        else {
            // Card should be hidden, so just return true now.
            return true 
        }
    }
        // If Card was never proven to be hidden through all filter groups, then it is shown. Return to_hide = False
        return false

}


/* Updates UI to display the active filters via the ADS-tags, aka 'facets', under the search bar.  */
function updateFacet(filter_group, item_name) {
    const all_path_cards = document.querySelectorAll('.search-div');
    

    // Replace the filter group's tag with the currently selected item name
                                                                                // license
    var filter_facet = document.getElementById('filter-facet-display-name-group-'+filter_group.toLowerCase());
    filter_facet.textContent = filter_group+": "+item_name;

    let ads_filter_component = filter_facet.closest('ads-tag');
    // Update tag's class
    if ((item_name == "All") || (item_name == "all")) {
        console.log(item_name,'in removing')
        ads_filter_component.classList.remove('not-all')
    }
    else {
        console.log(item_name,'in adding')
        ads_filter_component.classList.add('not-all')
    }

    // Apply search and filters to current parameters
            // deal with ads search promise
    document.getElementById('search-box').value().then((value) => { 
        let results_to_hide = applySearchAndFilters(all_path_cards, value); // apply active search & filter terms to the specified divs
        hideElements(all_path_cards,results_to_hide);
        updateShownNumber();                  // Update UI telling how many are displayed
    });
}


/* Not used anymore, constant facets.....could remove */
function removeFacet(tag) {
    const all_path_cards = document.querySelectorAll('.search-div');
     //////// Remove Facet
     document.getElementById('filter-'+tag).remove();

    ////////// Uncheck checkbox if applicable
        // get status of checkbox (true for checked, false for unchecked)
        const checkbox_element = document.querySelectorAll('ads-checkbox.'+tag)[0]
        checkbox_element.value().then((value) => { 
            if (value === true) {
                // uncheck it. NOT WORKING
                //>>>>????????????????????????????????????????????????????? ADS issue
                //checkbox_element.setAttribute('checked',true); // when setting and unsetting it freezes the checkbox element.
            

                //checkbox_element.removeAttribute('checked');
                checkbox_element.checked = false;
            }
        });

    // Remove 'clear filters' command if no filters left 
    let active_facets = document.querySelectorAll('ads-tag.filter-facet');
    if (active_facets.length === 0) {
        document.getElementById('tag-clear-btn').hidden = true;
    }

    // Apply search and filters to current parameters
        // deal with ads promise
        document.getElementById('search-box').value().then((value) => { 
             let results_to_hide = applySearchAndFilters(all_path_cards, value); // apply active search & filter terms to the specified divs
             hideElements(all_path_cards,results_to_hide);
             updateShownNumber();                  // Update UI telling how many are displayed
            },
        );

}

/* Not used anymore, constant facets.....could remove */
function addFacet(element) {
    const all_path_cards = document.querySelectorAll('.search-div');

     //////// Add Facet
     // Get 'tag' and 'display_tag' and filter_group
     let tag = null;
     let filter_group = null;

     const tags = element.classList.values();
     for (let t of tags) {
         if (t.includes('tag')) {
             tag = t;
             break;
         }
     };
     for (let t of tags) {
        if (t.includes('group')) {
            filter_group = t;
            break;
        }
    };


    // Make sure that this tag doesn't already exist (issue with ADS checkboxes, need to verify here otherwise we get repeating facets appearing)
    if (document.querySelectorAll('ads-tag#filter-'+tag).length > 0) {
        return //if it does, just leave without doing anything (no need, already exists)
    }


     let display_tag = element.name;
     document.querySelector('#current-tag-bar').insertAdjacentHTML(
         'beforeend',
         `
         <ads-tag href="#" class="filter-facet u-margin-left-1/2 u-margin-top-1/2 u-margin-bottom-1/2 `+filter_group+`" id="filter-${tag}">
             <span class="u-flex u-flex-row u-align-items-center u-gap-1/2">
                 <div class="filter-facet-display-name">${display_tag}</div>
                 <a onclick="removeFacet('${tag}')">
                     <span class="fal fa-times-circle"></span>
                 </a>
             </span>
         </ads-tag>
             `
     );

     // Show 'clear filters' command (if already shown this command does nothing.)
     document.getElementById('tag-clear-btn').hidden = false;

     // Apply search and filters to current parameters
        // deal with ads promise
        document.getElementById('search-box').value().then((value) => { 
            let results_to_hide = applySearchAndFilters(all_path_cards, value); // apply active search & filter terms to the specified divs
            hideElements(all_path_cards,results_to_hide);
            updateShownNumber();                  // Update UI telling how many are displayed
        });
}

/* Not used anymore, constant facets.....could remove */
function clearAllFilters() {
    // call removeFacet on each tag
    let active_facets = document.querySelectorAll('ads-tag.filter-facet');
    for (let facet of active_facets) {
        let tag  = facet.id.replace('filter-',''); // tag.id = filter-tag-databases   strip off 'filter-'
        removeFacet(tag);
    }
}


/* Search logic */
function searchByTitle(card,search_word_array) {   
    // Title of learning path --> title must include ALL search terms (any order or case)
    let card_title = card.querySelector('.search-title').innerHTML.toLowerCase();
    var title_serach_match = search_word_array.every(item => card_title.includes(item));
    if (!title_serach_match) {
        return true // hide it
    }
    else {
        return false // show it
    }
}

/* Calls both search & filter logic, and returns all rows that should be hidden as list */
function applySearchAndFilters(all_path_cards, search_string) {    
    // Skip search bits if no search string
    let skip_search = false;
    if ((typeof search_string) == 'undefined') {
        search_string='';
        skip_search=true; 
    }

    // Filter search term
    const search_word_array = search_string.toLowerCase().split(" ");   // 'MongoDB Arm Neoverse-N1' --> ['mongodb','arm','neoverse-n1']

    // store results to hide based on certain parameters
    let results_to_hide = [];

    for (let card of all_path_cards) {
        ////////////////////////////////////////////////////////////////
        // SEARCH
        if (!skip_search) {
            if (searchByTitle(card,search_word_array) && searchKeepPinnedrow(card)) { 
                results_to_hide.push(card); // set card to be hidden
            }
        }
        ////////////////////////////////////////////////////////////////
        // FILTER
        if (filter_card(card)) { // if we get back non-null from function, the card should be hidden
            results_to_hide.push(card); // set card to be hidden
        }

    }


    return results_to_hide
}


/* Called from search bar. Sanatizes input, applies logic, hides rows, updates UI */
function searchHandler(search_string) {
    // HANDLE if coming from ads search box (event.value) or URL (string)
    if (! (typeof search_string === 'string')) {
        search_string = search_string.value;
    }

    // Set page state to Browse, if not already
    setToBrowse();
    
    
    // Sanitize the input
    search_string = sanitizeInput(search_string);

    const all_path_cards = document.querySelectorAll('.search-div');

    // Apply search and filters to current parameters
    let results_to_hide = applySearchAndFilters(all_path_cards, search_string); // apply active search & filter terms to the specified divs
   
    // Hide specified elements 
    hideElements(all_path_cards,results_to_hide);

    // Update UI telling how many are displayed
    updateShownNumber();
}


/* Not called anymore......could remove */
function filterHandler(element) {
    /*      Called from ads-checkbox components themselves, triggered from a user press on checkbox        
                Update facets to appear
                Apply only updated filter to search results (show what isn't that matches & vice versa)
    */
    const all_path_cards = document.querySelectorAll('.search-div');
    
    // Set page state to Browse, if not already
    setToBrowse();

    // get status of checkbox (true for checked, false for unchecked)
    element.value().then((value) => {
        if (value === true) {
            // add 'checked' value to html
            addFacet(element,all_path_cards);
        }
        else {
            //?????????????????????????????????????????????????????????????????????????
            // This is being called when there is no facet. Strange behaivor with checkbox value being set strangely
            // ADS team to fix this problem.
            let tag = null;
            const tags = element.classList.values();
            for (let t of tags) {
                if (t.includes('tag')) {
                    tag = t;
                    break;
                }
            };
            removeFacet(tag);
        }
    });
}

/* Called from radio filters. Updates facets, which then applies logic, hides rows, updates UI  */
function filterHandler_radio(element) {
    /*      Called from 'input' components themselves, triggered from a user press on radio
                Add Facet for correct one
                Remove all other facets
    */
    const all_path_cards = document.querySelectorAll('div.search-div');
    
    // Set page state to Browse, if not already
    setToBrowse();

    // Update the facet
    var item_name  = element.getAttribute('data-display-name');
    var group_name  = element.getAttribute('data-group-display-name');
    updateFacet(group_name,item_name);

}



function ifNeededMoveFiltersToMobileOrDesktop(state_is_below_breakpoint) {
    let just_moved_below_breakpoint = window.innerWidth < 768;
    let filters_to_move = document.getElementById('filters-movable');
    const filter_destination = just_moved_below_breakpoint ? document.getElementById('mobile-filters') : document.getElementById('desktop-filters');

    // If breakpoint crossed, move filters to their correct location
    if (just_moved_below_breakpoint !== state_is_below_breakpoint) {
        filter_destination.appendChild(filters_to_move);
        return just_moved_below_breakpoint;
    }
    return state_is_below_breakpoint; // return true/false state to check if breakpoint crossed in future
}



/* Does three things at DOMContentLoad:
        1. Assigns inputChangeHandler to searchbox
        2. Moves filters to/from desktop/mobile
        3. Activates URL search/filters
*/
document.addEventListener("DOMContentLoaded", function () {

    // 1
    // Assign inputChangeHandler to search box
    const search_box = document.getElementById('search-box');
    search_box.inputChangeHandler = searchHandler;    

    // 2
    // Move filters to match users current viewport size (desktop or mobile)     
    let state_is_below_breakpoint = window.innerWidth < 768;
    state_is_below_breakpoint = ifNeededMoveFiltersToMobileOrDesktop(state_is_below_breakpoint); // Check at page load if they should be moved to mobile (default in desktop)
    
    // Listen for window resizes and move the filters if breakpoint is crossed
    let t_out;
    window.addEventListener('resize', function() {
        clearTimeout(t_out);
        t_out = setTimeout(function() {
            state_is_below_breakpoint = ifNeededMoveFiltersToMobileOrDesktop(state_is_below_breakpoint); // update current breakpoint value
        }, 200);
    });


    // 3
    // Handle search term from URL
        /* Support 3 situations; search, filtering, and both:
            page.html?search=mySearchTerm
            page.html?filter=row1,row2,row3  // TO DO like learning paths
            page.html?search=mySearchTerm&pin=row1,row2,row3 // TO DO like learning paths
        */
    let url_str = window.location.search;
    if (url_str.includes('?')) {    URLsearchAndfiltering(url_str);    }



});