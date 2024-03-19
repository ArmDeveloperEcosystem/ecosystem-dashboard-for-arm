
/* These analytics are implemented to track 100% anonymous clicks, and will be used for improving the product ONLY.*/


function getActiveFacets() {
    let filter_types = ['license','category'];
    let active_filters = []; // to fill out this list
    for (let filter of filter_types) {
        let radio_buttons = document.querySelectorAll('.group-'+filter+'.checkable-input');
        let filter_active = 'All' // Default to all
        for (let radio of radio_buttons) {
            if (radio.checked) {
                filter_active = radio.getAttribute('data-display-name');
                break;
            }
        }
        active_filters.push(filter_active);
    }
    // active_filters = ['All','OS']

    let facet_tracking_string = '';
    for (var i = 0; i < filter_types.length; i++) {
        facet_tracking_string = facet_tracking_string+filter_types[i]+': '+active_filters[i]+', ';
    }

    return facet_tracking_string
}

function trackSearchInteraction(reason) {

    // Get search query (inside promise, continue the rest of this inside the promise)
    document.getElementById('search-box').value().then((value) => { 
        let current_search = value || 'none';

        console.log('Search')
        console.log('Tracking search:',current_search);               
        console.log('Facets: ',getActiveFacets())
        console.log('reason: ',reason)

        _satellite.track('ecosystem-search', {
            'facet-active-names'   : getActiveFacets(),
            'search-current-query' : current_search,
            'search-call-reason'   : reason
        });

    });
}


function trackFacetInteraction(){

    // Get search query (inside promise, continue the rest of this inside the promise)
    document.getElementById('search-box').value().then((value) => { 
        let current_search = value || 'none';
        
        console.log('FACETS')
        console.log('Tracking search:',current_search);               
        console.log('Facets: ',getActiveFacets())

        // Send tracking data  
        _satellite.track('facet-interaction', {
            'facet-active-names'   : getActiveFacets(),
            'search-current-query' : current_search
            });
    });
}

function trackGeneralContentInteraction(content_tracking_name,package_name) {
    document.getElementById('search-box').value().then((value) => { 
        let current_search = value || 'none';
        

        console.log('CONTENT');
        console.log('datatrack ',content_tracking_name);
        console.log('package-name ',package_name)
        console.log('facets ',getActiveFacets());
        console.log('search ',current_search);
        

        _satellite.track('content-interaction', {   
            'data-track-name'       : content_tracking_name,
            'package-name'          : package_name,
            'facet-active-names'    : getActiveFacets(),
            'search-current-query'  : current_search
            });
        });
}


function trackHeaderInteraction(type,name){
    // type = 'header-mainnav-clicks' or 'header-subnav-clicks' or 'header-social-clicks' or 'header-other-clicks' or 'header-breadcrumb-clicks'
    // name = like 'Theme change' or 'Discord', etc.
    _satellite.track('content-interaction', {   
        'data-track-type'     : type,
        'data-track-location' : 'global-nav',
        'data-track-name'     : name
    });
}


// wait for all DOM elements to be loaded first, then can assign event listeners to them.
document.addEventListener("DOMContentLoaded", function() {  

    //
    //  Search & Filter
    //  ===================
    let search_box = document.getElementById('search-box');

    // When user deselects search box (is clicking on something else)
    search_box.addEventListener('blur', () => {
        trackSearchInteraction('deselected_search_bar');
    });

    // After 2 seconds when a user enters data
    let timer; 
    const input_delay = 2000; //  milliseconds
    search_box.addEventListener('input', function() {
        if (timer) clearTimeout(timer);         // Clear timer if input detected

        timer = setTimeout(function() {         
            trackSearchInteraction('delay_after_search_change');
        }, input_delay);
    });


    let filter_facet_elements = document.querySelectorAll('.checkable-input');            
    for (let facet of filter_facet_elements) {
        facet.addEventListener("click", () => {
            trackFacetInteraction();                            
        });
    }


    //
    //  Row click
    //  ===================
    let main_package_rows = document.querySelectorAll('tr.main-sw-row');            
    for (let row of main_package_rows) {
        row.addEventListener("click", () => {

            document.getElementById('search-box').value().then((value) => { 
                let current_search = value || 'none';



                console.log('ROW CLICKED')
                console.log('search_result_name clicked',row.getAttribute('data-title'))
                console.log('Tracking search:',current_search);               
                console.log('Facets: ',getActiveFacets())
        
                // Send tracking data  
                _satellite.track('eco-sw-result-click', {
                    'facet-active-names'   : getActiveFacets(),
                    'search-query' : current_search,
                    'search_result_name_clicked' : row.getAttribute('data-title'), // MongoDB
                    });
            });
        });
    }


    //
    //  Any package's content interaction
    //  =================================
        // Download button clicked
        let download_icons = document.querySelectorAll('a.download-icon-a');
        for (let download of download_icons) {
            download.addEventListener("click", () => {
                let package_name = download.closest('tr').getAttribute('data-title');
                trackGeneralContentInteraction('download_button',package_name);
            });
        }
    

        // GitHub issue tracking
        let github_issue_links = document.querySelectorAll('a.github-issue-update-link');
        for (let gh_link of github_issue_links) {
            gh_link.addEventListener("click", () => {
                let package_name = gh_link.closest('table').closest('tr').previousElementSibling.getAttribute('data-title');
                trackGeneralContentInteraction('github_edit_package_click',package_name);
            });
        }

        // Getting started links
        let getting_started_links = document.querySelectorAll('a.getting-started-resource');
        for (let link of getting_started_links) {
            let link_type = link.getAttribute('data-source-type');
            link.addEventListener("click", () => {
                let package_name = link.closest('tr').previousElementSibling.getAttribute('data-title');
                trackGeneralContentInteraction('quick_start_guide_click__'+link_type,package_name);
            });
        }

        // Contribute CTA
        let contribute_cta = document.getElementById('contribute-link-to-readme');
        contribute_cta.addEventListener("click", () => {
            trackGeneralContentInteraction('guidelink_link_click','CONTRIBUTE NEW PACKAGE');
        });
     

});

    

    
