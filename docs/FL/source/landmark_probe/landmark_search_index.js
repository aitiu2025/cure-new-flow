
/**
 * Initializes the Select2 component for a document category field with enhanced screen reader accessibility.
 * This function dynamically sets the `aria-label` attribute of the Select2's search field to ensure it is accessible
 * to screen readers. It targets elements based on a provided suffix, allowing for flexible use across multiple search types tabs.
 *
 * @param {string} suffix - The suffix appended to the IDs of the select and container elements to uniquely identify them.
 */
function initializeDocumentCategorySelect2(suffix) {
    var selectId = "select#documentCategory-" + suffix;
    var containerId = "#container-doc-categ-" + suffix;

    $(selectId).select2({
        dropdownParent: $(containerId)
    }).maximizeSelect2Height();

    $(selectId).one("select2:open", function (event) {
        var $searchfield = $("input.select2-search__field", $(containerId));
        $searchfield.attr("aria-label", "Type to search or filter document category options");
    });
}

function AdjustDateRange(suffix) {
    var lastNumOfDaysControl = $('#lastNumOfDays-' + suffix);
    var beginDate = $('#beginDate-' + suffix);
    var endDate = $('#endDate-' + suffix);

    if (lastNumOfDaysControl.val() == 0) {
        $('#beginDate-' + suffix + ",#endDate-" + suffix).val('');
    }
    else {
        var val = lastNumOfDaysControl.val();
        var regex = /([0-9]+)([DMY]{1})/;
        var match = val.match(regex);

        if (match.length > 0) {
            var type = "day";
            switch (match[2]) {
                case "M":
                    type = "month";
                    break;
                case "Y":
                    type = "year";
                    break;
            }
            beginDate.val(moment().subtract(match[1], type).format("MM/DD/YYYY"));
        }

        endDate.val(today);
    }
}

var waitString = '';

function ClearMe(textbox) {
    if ((textbox.value.indexOf('Result') > -1) || (textbox.value.indexOf('Instrument') > -1) || (textbox.value.indexOf('Book') > -1)) {
        textbox.value = '';
        $(textbox).css('color', '#000');
    }
}

function CheckForReset(textbox) {
}

function ToggleExciseTaxInclude(element, suffix, showMobile) {
    if (showMobile) {
        var id = "#mobileHomesOnly_" + suffix;
        if (element.checked) {
            $(id).show();
        }
        else {
            var cbId = "#mobileHomesOnlyCB_" + suffix;
            $(cbId).removeAttr('checked')
            $(id).hide();
        }
    }
}

function ToggleSearchSection(item) {
    $('#hideSearch, #showSearch').removeClass("hide");
    if (item == 'hide') {
        $('#searchSection, #hideSearch').hide(500);
    }
    else {
        $('#showSearch').addClass("hide");
        $('#hideSearch').show();
        $('#searchSection').show(500);
    }
}

function ToggleCurrentSearchHelp() {
    var currentSearch, currentHelp;
    $('div [id^=searchCriteria]').not('[id$=-tab]').each(function () {
        if ($(this).is(':visible')) {
            currentHelp = $('#' + $(this).data('helpSection'));
            if (currentHelp.is(":visible")) {
                currentHelp.hide(500);
            }
            else {
                currentHelp.show(500);
            }
        }
    });
}

function ClearForm(form) {

    var subDiv = $('.legalDocTableTextInput.select2');
    if (subDiv.length > 0) {
        //19963 - Clear Form/Clear All not Clearing the Subdivision
        subDiv.val('').trigger('change');
    }

    if (form != 'all') {
        $('#' + form)[0].reset();
        $('#' + form).find('.documenttypeidshidden').val('');
    }
    else {
        $('.documenttypeidshidden').val('');

        $('[id$=SearchForm]').each(function (index) {
            $(this)[0].reset();
        });
    }


}

function LoadCaptcha(captcha) {
    if (typeof grecaptcha === 'undefined')
        return;

    if (!captcha.data().loaded) {
        var item = captcha[0];
        item.innerHTML = '';
        item.captcha = grecaptcha.render(item, { sitekey: captcha.data().sitekey });
        captcha.data().loaded = true;
    }
}

function SearchNavMakeActive(item, captcha) {
    var itemToShow = item.data().toshow;
    $('#videoHelpSearch').data('type', itemToShow.replace('searchCriteria', ''));

    if (captcha.length > 0) {
        $.post(site + 'Search/ShowCaptcha', function (result) {
            if (result == "True")
                captcha.show();
            else
                captcha.hide();

            if (typeof grecaptcha === 'undefined' || !grecaptcha.render) {
                window.setTimeout(function () {
                    LoadCaptcha(captcha);
                }, 500);
            }
            else
                LoadCaptcha(captcha);
        });
    }

    var toshow = $("#" + item.data("toshow"));
    if (toshow.length > 0) {
        $(".searchNav").removeClass('active');
        $("[id^=searchCriteria]").addClass("hide");
        $("#" + item.data("toshow")).removeClass("hide");
        item.addClass('active');
    }

    var helpSection = $('#' + item.attr('data-toshow')).find('.helpSection');
    if (helpSection.length > 0) {
        $('#helpSection,#helpSectionFull').html(helpSection.html());
        $('#helpSection,#helpInfoSection').show();
        $('#helpSectionFull').hide();
    }
    else {
        $('#helpSection,#helpSectionFull,#helpInfoSection').hide();
        return;
    }

    $('#helpSection').contents().each(function () {
        if (!$(this).hasClass('alert-heading'))
            $(this).remove();
    });

    function showHideHelpSection() {
        $('#helpSection, #helpSectionFull').toggle();
    }

    $('#helpSection > .alert-heading, #helpSectionFull > .alert-heading, #helpInfoButton')
        .off()
        .click(function () {
            showHideHelpSection();
        }).hover(function () {
            $(this).parent().addClass('helpSectionOver');
        }, function () {
            $(this).parent().removeClass('helpSectionOver');
        }).on('keydown', function (e) {
            if (e.key === ' ') {
                e.preventDefault(); // Prevent the default action to stop scrolling
                showHideHelpSection();
            }
        });

    if (openHelpText)
        $('#helpSection>.alert-heading').click();
}

$(document).keypress(function (e) {
    if (e.which == "13") {
        var theForm = this.activeElement.form;
        var activeTab = theForm.attributes.id.value;

        switch (activeTab) {
            case 'nameSearchForm':
                var b = $('.nameSearchSubmit');
                if (b.length > 0)
                    b.click();
                else
                    SubmitSearch('nameSearchForm', 'NameSearch', 'Name');
                break;
            case 'caseNumberSearchForm':
                SubmitSearch('caseNumberSearchForm', 'CaseNumberSearch', 'CaseNumber');
                break;
            case 'parcelIdSearchForm':
                SubmitSearch('parcelIdSearchForm', 'ParcelIdSearch', 'ParcelId');
                break;
            case 'recordDateSearchForm':
                SubmitSearch('recordDateSearchForm', 'RecordDateSearch', 'RecordDate');
                break;
            case 'instrumentNumberSearchForm':
                SubmitSearch('instrumentNumberSearchForm', 'InstrumentNumberSearch', 'InstrumentNumber');
                break;
            case 'legalSearchForm':
                SubmitSearch('legalSearchForm', 'LegalSearch', 'Legal');
                break;
            case 'legalDocSearchForm':
                SubmitSearch('legalDocSearchForm', 'LegalDocSearch', 'LegalDoc');
                break;
            case 'quickSearchForm':
                SubmitSearch('quickSearchForm', 'QuickSearch', 'QuickSearch');
            case 'documentTypeSearchForm':
                SubmitSearch('documentTypeSearchForm', 'DocumentTypeSearch', 'DocumentType');
                break;
            case 'bookPageSearchForm':
                SubmitSearch('bookPageSearchForm', 'BookPageSearch', 'BookPage');
                break;
            case 'considerationSearchForm':
                SubmitSearch('considerationSearchForm', 'ConsiderationSearch', 'Consideration');
                break;
            case 'marriageSearchForm':
                SubmitSearch('marriageSearchForm', 'MarriageSearch', 'Marriage', 'chkMarriageDateInsteadOfRecordDate');
                break;
            case 'alphaIndexSearchForm':
                SubmitSearch('alphaIndexSearchForm', 'AlpahIndex', 'Name');
                break;

            default:
                var url = $(theForm).data("url");
                var suffix = $(theForm).data("suffix");

                if (url && url === "AdditionalSearch") {
                    SubmitSearch(activeTab, url, suffix)
                }
                break;
        }
    }
});



function getQueryVariable(queryVar) {
    //debugger;
    var query = window.location.search.substring(1);
    var vars = query.split('&');
    for (var i = 0; i < vars.length; i++) {
        var pair = vars[i].split('=');
        if (decodeURIComponent(pair[0]) == queryVar) {
            return decodeURIComponent(pair[1]);
        }
    }
    return '';
}

function ValidateEntry(control, pattern) {
    //16490 - LM Web Advanced Legal Search should not require 'Building' parm
    var rtn = false;
    if (control != null && control.length > 0) {
        if (control.val() && Trim(control.val()).length > 0 && RegExCheck(control.val(), pattern)) {
            rtn = true;
        }
        else {
            control[0].focus();
            rtn = false;
        }
    }
    return rtn;
}

$.fn.serializeObject = function () {
    var o = {};
    var a = this.serializeArray();
    $.each(a, function () {
        if (o[this.name] !== undefined) {
            if (!o[this.name].push) {
                o[this.name] = [o[this.name]];
            }
            o[this.name].push(this.value || '');
        } else {
            o[this.name] = this.value || '';
        }
    });
    return o;
};

function SetCriteria(url, suffix, formName) {
    var criteria = {};
    if (suffix.indexOf("AdditionalSearch") >= 0) {
        criteria.QueryId = $('#' + formName).find('.queryid').val();
        $('#' + formName)
            .find('.searchmiscinput')
            .each(function () {
                var t = $(this);

                if (!criteria.Item)
                    criteria.Item = [];

                if (t.attr('required') && !t.val()) {
                    criteria = "NOGO";
                    return false;
                }

                criteria.Item.push({ Name: t.attr('name'), Value: t.val() });
            });

        criteria.ItemsJSON = JSON.stringify(criteria.Item);
        // if (invalidTypeIns == '') { //Please select or enter a valid document type.'
        //     ThrowValidationError($('#Lot'), $('#legalDocError'));
        // }
        // else { //One or more document types are invalid.
        //     ThrowValidationError($('#Lot'), $('#docTypeTextError-' + suffix));
        // }
        // criteria = "NOGO";
    }
    else if (suffix == 'Torren') {
        criteria = $('#torrenSearchForm').serializeObject();
    }
    else {
        var mobileHomesOnly = false;

        var mobileHomeElem = $('#mobileHomesOnlyCB_' + suffix);
        if (mobileHomeElem != null) {
            mobileHomesOnly = mobileHomeElem.is(":checked");
        }

        var locBeginDate, locEndDate;
        var dateCount = $("[id$=Date-" + suffix + "]").length;
        if (dateCount > 0) {
            locBeginDate = GetDateValue('beginDate-' + suffix);
            locEndDate = GetDateValue('endDate-' + suffix);
        }
        var matchType = $('#matchType-' + suffix).val();
        var docTypes = $('#documentTypeIds-' + suffix).length > 0 ? $('#documentTypeIds-' + suffix).val() : '';

        var invalidTypeIns = ''; //a list of all text typed in that is not a valid doc type
        var txtDocumentTypes = $('#documentType-' + suffix);
        if (txtDocumentTypes.length == 1 && txtDocumentTypes.val() != "") {
            //18082 -  Web search for advanced legal requires all parsed legal fields to be completed prior to returning a successful search.
            //18078 - Document Type field in Search doesn't allow a user to type in a Doc Type
            //docTypes is a mixture of items chosen by checkbox and items explicitly typed in.  To be correct it depends on the type-ins to be followed by a ‘select’ and
            //additional items checked.  This code throws away that fragile result, and builds a list directly from items in textbox.

            var bFound = false;
            var comma = '';
            var idsOfTypedInText = '';
            var currentText = '';
            currentText = $('#documentType-' + suffix).val();
            var currentTextList = currentText.split(",");
            for (var i = 0; i < currentTextList.length; i++) {
                bFound = false;
                var txtBoxCode = currentTextList[i].toUpperCase();
                txtBoxCode = txtBoxCode.trim();

                for (j in docTypeArray) {
                    var arrElement = docTypeArray[j];
                    if (arrElement.code != null) {
                        //-18538: WEB - Document type with & gives invalid doc type warning.
                        var elCode = arrElement.code.replace(/&amp;/g, '&').toUpperCase();
                        if (elCode == txtBoxCode) {
                            bFound = true;
                            idsOfTypedInText += comma + arrElement.id;
                            comma = ",";
                        }
                    }
                }
                if (bFound == false && txtBoxCode != '') {
                    invalidTypeIns += txtBoxCode + ", ";
                }
            }
            if (docTypes != "") {
                docTypes += ",";
            }
            docTypes += idsOfTypedInText.toUpperCase();//just be safe combine the two list
            var currentTextArray = docTypes.split(",");
            currentTextArray = currentTextArray.unique(); //strip away duplicates
            currentTextArray = currentTextArray.sort();
            docTypes = currentTextArray.join(",");
        }

        var townName = ""; //most but not all searchs support town
        var townNameId = $('#idTownNameList-' + suffix);
        if (townNameId.length > 0) //Jquery list lenght > 0
        {
            townName = townNameId.val();
        }

        switch (url) {
            case "GetMatchingNames":
            case "NameSearch":
                var _nameControl = $("#name-" + suffix);
                ClearValidationErrors(_nameControl, $('#nameError-' + suffix));
                ClearValidationErrors(_nameControl, $('#docTypeTextError-' + suffix));

                if (ValidateEntry(_nameControl, NAME_CHARS) && invalidTypeIns == '') {
                    var names = [];
                    var ids = [];
                    if ($('#nameSearchModal').is(":visible")) {
                        var all = $('#matchingNamesList input[value="ALL"]').is(":checked");

                        $('#matchingNamesList ' + (all ? "input" : "input:checked")).not('input[value="ALL"]').each(function () {
                            ids.push($(this).val());
                            names.push($(this).data().name);
                        });
                    }

                    criteria = {
                        searchLikeType: matchType, type: $('#partyType').val(), name: _nameControl.val(), doctype: docTypes, bookType: $('#bookType-name').val(),
                        beginDate: locBeginDate, endDate: locEndDate, recordCount: $('#numberOfRecords-' + suffix).val(), exclude: $('#excludeDocType_' + suffix).is(':checked'), ReturnIndexGroups: $('#indexgroup_' + suffix).is(':checked'), townName: townName,
                        selectedNamesIds: ids.join('|||'), includeNickNames: $('#includeNicknames').is(':checked'), selectedNames: names.join('|||'), mobileHomesOnly: mobileHomesOnly
                    };
                }
                else {
                    if (invalidTypeIns == '') {
                        ThrowValidationError(_nameControl, $('#nameError-' + suffix));
                    }
                    else {
                        ThrowValidationError(_nameControl, $('#docTypeTextError-' + suffix));
                    }

                    criteria = "NOGO";
                }
                break;
            case "MarriageSearch":
                var _nameControl = $("#name-" + suffix);
                var chkMarriageDateInsteadOfRecordDate = $('#chkMarriageDateInsteadOfRecordDate').is(':checked');
                ClearValidationErrors(_nameControl, $('#nameError-' + suffix));

                if (true || ValidateEntry(_nameControl, NAME_CHARS)) {
                    criteria = { type: $('#partyType').val(), name: _nameControl.val(), doctype: docTypes, beginDate: locBeginDate, endDate: locEndDate, recordCount: $('#numberOfRecords-' + suffix).val(), exclude: $('#excludeDocType_' + suffix).is(':checked'), ReturnIndexGroups: $('#indexgroup_' + suffix).is(':checked'), MarriageDateInsteadOfRecordDate: chkMarriageDateInsteadOfRecordDate, townName: townName, mobileHomesOnly: mobileHomesOnly };
                }
                else {
                    ThrowValidationError(_nameControl, $('#nameError-' + suffix));
                    criteria = "NOGO";
                }
                break;
            case "DocumentTypeSearch":
                var docTypeControl = $('#documentType-' + suffix);
                ClearValidationErrors(docTypeControl, $('#docTypeError-' + suffix));
                ClearValidationErrors(docTypeControl, $('#docTypeTextError-' + suffix));
                var bValid = true;
                if (docTypes == '' || invalidTypeIns != '') {
                    bValid = false;
                }
                if (bValid == true) {
                    criteria = { doctype: docTypes, beginDate: locBeginDate, endDate: locEndDate, recordCount: $('#numberOfRecords-' + suffix).val(), exclude: $('#excludeDocType_' + suffix).is(':checked'), ReturnIndexGroups: $('#indexgroup_' + suffix).is(':checked'), townName: townName, mobileHomesOnly: mobileHomesOnly };
                }
                else {
                    if (invalidTypeIns != '') { //Please select or enter a valid document type.'
                        ThrowValidationError(docTypeControl, $('#docTypeError-' + suffix));
                    }
                    else { //One or more document types are invalid.
                        ThrowValidationError(docTypeControl, $('#docTypeTextError-' + suffix));
                    }
                    criteria = "NOGO";
                }
                break;
            case "BookPageSearch":
                var bookControl = $('#book');
                var pageControl = $('#page');
                var formOk = true;
                if (!ValidateEntry(bookControl, BOOK_NUMBER_CHARS)) {
                    formOk = false;
                    ThrowValidationError(bookControl, $('#bookError-' + suffix));
                }
                if (!ValidateEntry(pageControl, BOOK_NUMBER_CHARS)) {
                    formOk = false;
                    ThrowValidationError(pageControl, $('#pageError-' + suffix));
                }
                if (formOk) {
                    criteria = { bookType: $('#bookType').val(), book: bookControl.val(), page: pageControl.val(), exclude: $('#excludeDocType_' + suffix).is(':checked'), ReturnIndexGroups: $('#indexgroup_' + suffix).is(':checked'), recordCount: $('#numberOfRecords-' + suffix).val(), mobileHomesOnly: mobileHomesOnly };
                }
                else {
                    criteria = "NOGO";
                }
                break;
            case "ConsiderationSearch":// validate for decimal
                if (Trim($('#lowerBound').val()).length == 0) {
                    $('#lowerBound').val('0.00');
                }
                if (Trim($('#upperBound').val()).length == 0) {
                    $('#upperBound').val('0.00');
                }
                if (!RegExCheck($('#lowerBound').val(), DECIMAL_CHARS)) {
                    ThrowValidationError($('#lowerBound'), $('#lowerBoundError'));
                    criteria = "NOGO";
                }
                if (!RegExCheck($('#upperBound').val(), DECIMAL_CHARS)) {
                    ThrowValidationError($('#upperBound'), $('#upperBoundError'));
                    criteria = "NOGO";
                }
                if (($('#lowerBound').val() == '0.00') && ($('#upperBound').val() == "0.00")) {
                    ThrowValidationError($('#upperBound'), $('#upperBoundError'));
                    criteria = "NOGO";
                }
                if (invalidTypeIns != '') {
                    ThrowValidationError($('#upperBound'), $('#docTypeTextError-' + suffix));
                    criteria = "NOGO";
                }
                if (criteria != "NOGO") {
                    criteria = { lowerBound: $('#lowerBound').val(), upperBound: $('#upperBound').val(), doctype: docTypes, beginDate: locBeginDate, endDate: locEndDate, exclude: $('#excludeDocType_' + suffix).is(':checked'), ReturnIndexGroups: $('#indexgroup_' + suffix).is(':checked'), recordCount: $('#numberOfRecords-' + suffix).val(), townName: townName, mobileHomesOnly: mobileHomesOnly };
                }
                break;
            case "InstrumentNumberSearch":
                var _instrumentNumber = $('#instrumentNumber');
                ClearValidationErrors(_instrumentNumber, $('#instrumentNumberError'));

                var bookTypeVal = "0";
                if ($('#matchType-BookType').length == 1) {
                    bookTypeVal = $('#matchType-BookType').val();
                }

                if (ValidateEntry(_instrumentNumber, ZIP_CHARS)) {
                    criteria = { searchLikeType: matchType, instrumentNumber: _instrumentNumber.val(), exclude: $('#excludeDocType_' + suffix).is(':checked'), ReturnIndexGroups: $('#indexgroup_' + suffix).is(':checked'), recordCount: $('#numberOfRecords-' + suffix).val(), bookType: bookTypeVal, mobileHomesOnly: mobileHomesOnly };
                }
                else {
                    ThrowValidationError(_instrumentNumber, $('#instrumentNumberError'));
                    criteria = "NOGO";
                }
                break;
            case "CaseNumberSearch":
                var _caseNumberControl = $('#caseNumber');
                ClearValidationErrors(_caseNumberControl, $('#caseNumberError'));
                ClearValidationErrors(_caseNumberControl, $('#docTypeTextError-' + suffix));

                if (ValidateEntry(_caseNumberControl, ADDRESS_CHARS) && invalidTypeIns == '') {
                    criteria = { searchLikeType: matchType, caseNumber: _caseNumberControl.val(), doctype: docTypes, beginDate: locBeginDate, endDate: locEndDate, exclude: $('#excludeDocType_' + suffix).is(':checked'), ReturnIndexGroups: $('#indexgroup_' + suffix).is(':checked'), recordCount: $('#numberOfRecords-' + suffix).val(), townName: townName, mobileHomesOnly: mobileHomesOnly };
                }
                else {
                    if (invalidTypeIns == '') { //Please select or enter a valid document type.'
                        ThrowValidationError(_caseNumberControl, $('#caseNumberError'));
                    }
                    else { //One or more document types are invalid.
                        ThrowValidationError(_caseNumberControl, $('#docTypeTextError-' + suffix));
                    }
                    criteria = "NOGO";
                }
                break;
            case "LegalSearch":
                var _legalControl = $('#legal');
                ClearValidationErrors(_legalControl, $('#legalError'));
                ClearValidationErrors(_legalControl, $('#docTypeTextError-' + suffix));
                //debugger;
                if (ValidateEntry(_legalControl, ADDRESS_CHARS) && invalidTypeIns == '') {
                    criteria = { searchLikeType: matchType, legal: _legalControl.val(), doctype: docTypes, beginDate: locBeginDate, endDate: locEndDate, exclude: $('#excludeDocType_' + suffix).is(':checked'), ReturnIndexGroups: $('#indexgroup_' + suffix).is(':checked'), recordCount: $('#numberOfRecords-' + suffix).val(), townName: townName, mobileHomesOnly: mobileHomesOnly };
                }
                else {
                    if (invalidTypeIns == '') { //Please select or enter a valid document type.'
                        ThrowValidationError(_legalControl, $('#legalError'));
                    }
                    else { //One or more document types are invalid.
                        ThrowValidationError(_legalControl, $('#docTypeTextError-' + suffix));
                    }
                    criteria = "NOGO";
                }
                break;
            case "LegalDocSearch":
                var _legalDocControl = $('#lot-searchdocinput');
                ClearValidationErrors(_legalDocControl, $('#legalDocError'));
                ClearValidationErrors(_legalDocControl, $('#docTypeTextError-' + suffix));
                //debugger;

                var ok = false;

                ok = ok || ValidateEntry($('#lot-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#block-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#unit-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#building-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#subdivision-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#comment-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#section-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#township-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#range-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#description-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#addressline1-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#addressline2-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#streetnumber-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#streetname-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#streetsuffix-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#streetdirection-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#city-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#state-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#zip-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#platbook-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#platpage-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#folionumber-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#foliotype-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#period-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#week-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#apt-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#phase-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#landlot-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#district-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#propertysection-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#condo-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#subid-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#legal-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#quarter-searchdocinput'), ADDRESS_CHARS);

                ok = ok || ValidateEntry($('#jurisdiction-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#levycode-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#shortplatnumber-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#rightofway-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#easement-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#ownername-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#legaltitle-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#owneraddress1-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#owneraddress2-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#ownerstreetnumber-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#ownerstreetname-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#ownerstreetsuffix-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#ownerstreetdirection-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#ownercity-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#ownerstate-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#ownerzip-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#textfield1-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#textfield2-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#textfield3-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#textfield4-searchdocinput'), ADDRESS_CHARS);
                ok = ok || ValidateEntry($('#textfield5-searchdocinput'), ADDRESS_CHARS);


                //debugger;
                if (ok && invalidTypeIns == '') {
                    criteria = {
                        searchLikeType: matchType, legalDoc: _legalDocControl.val(), docType: docTypes, beginDate: locBeginDate, endDate: locEndDate, exclude: $('#excludeDocType_' + suffix).is(':checked'), ReturnIndexGroups: $('#indexgroup_' + suffix).is(':checked'), recordCount: $('#numberOfRecords-' + suffix).val()
                        , Lot: $('#lot-searchdocinput').val()
                        , Block: $('#block-searchdocinput').val()
                        , Unit: $('#unit-searchdocinput').val()
                        , Building: $('#building-searchdocinput').val()
                        , Subdivision: $('#subdivision-searchdocinput').val() ? $('#subdivision-searchdocinput').val() : ''
                        , Comment: $('#comment-searchdocinput').val()
                        , Section: $('#section-searchdocinput').val()
                        , Township: $('#township-searchdocinput').val()
                        , Range: $('#range-searchdocinput').val()
                        , Description: $('#description-searchdocinput').val()
                        , AddressLine1: $('#addressline1-searchdocinput').val()
                        , AddressLine2: $('#addressline2-searchdocinput').val()
                        , StreetNumber: $('#streetnumber-searchdocinput').val()
                        , StreetName: $('#streetname-searchdocinput').val()
                        , StreetSuffix: $('#streetsuffix-searchdocinput').val()
                        , StreetDirection: $('#streetdirection-searchdocinput').val()
                        , City: $('#city-searchdocinput').val()
                        , State: $('#state-searchdocinput').val()
                        , Zip: $('#zip-searchdocinput').val()
                        , PlatBook: $('#platbook-searchdocinput').val()
                        , PlatPage: $('#platpage-searchdocinput').val()
                        , FolioNumber: $('#folionumber-searchdocinput').val()
                        , FolioType: $('#foliotype-searchdocinput').val()
                        , Period: $('#period-searchdocinput').val()
                        , Week: $('#week-searchdocinput').val()
                        , Apt: $('#apt-searchdocinput').val()
                        , Phase: $('#phase-searchdocinput').val()
                        , LandLot: $('#landlot-searchdocinput').val()
                        , District: $('#district-searchdocinput').val()
                        , PropertySection: $('#propertysection-searchdocinput').val()
                        , Condo: $('#condo-searchdocinput').val()
                        , SubID: $('#subid-searchdocinput').val()
                        , Legal: $('#legal-searchdocinput').val()
                        , Quarter: $('#quarter-searchdocinput').val()

                        , Jurisdiction: $('#jurisdiction-searchdocinput').val()
                        , LevyCode: $('#levycode-searchdocinput').val()
                        , ShortPlatNumber: $('#shortplatnumber-searchdocinput').val()
                        , RightOfWay: $('#rightofway-searchdocinput').val()
                        , Easement: $('#easement-searchdocinput').val()
                        , OwnerName: $('#ownername-searchdocinput').val()
                        , LegalTitle: $('#legaltitle-searchdocinput').val()
                        , OwnerAddress1: $('#owneraddress1-searchdocinput').val()
                        , OwnerAddress2: $('#owneraddress2-searchdocinput').val()
                        , OwnerStreetNumber: $('#ownerstreetnumber-searchdocinput').val()
                        , OwnerStreetName: $('#ownerstreetname-searchdocinput').val()
                        , OwnerStreetSuffix: $('#ownerstreetsuffix-searchdocinput').val()
                        , OwnerStreetDirection: $('#ownerstreetdirection-searchdocinput').val()
                        , OwnerCity: $('#ownercity-searchdocinput').val()
                        , OwnerState: $('#ownerstate-searchdocinput').val()
                        , OwnerZip: $('#ownerzip-searchdocinput').val()
                        , TextField1: $('#textfield1-searchdocinput').val()
                        , TextField2: $('#textfield2-searchdocinput').val()
                        , TextField3: $('#textfield3-searchdocinput').val()
                        , TextField4: $('#textfield4-searchdocinput').val()
                        , TextField5: $('#textfield5-searchdocinput').val()
                        , ExactQuarterSearch: $('#exactQuarterSearch').is(':checked')
                        , mobileHomesOnly: mobileHomesOnly
                    };
                }
                else {
                    $('#Lot').focus();
                    if (invalidTypeIns == '') { //Please select or enter a valid document type.'
                        ThrowValidationError($('#Lot'), $('#legalDocError'));
                    }
                    else { //One or more document types are invalid.
                        ThrowValidationError($('#Lot'), $('#docTypeTextError-' + suffix));
                    }
                    criteria = "NOGO";
                }
                break;
            case "ParcelIdSearch":
                var _parcelIdControl = $('#parcelId');
                ClearValidationErrors(_parcelIdControl, $('#parcelIdError'));
                ClearValidationErrors(_parcelIdControl, $('#docTypeTextError-' + suffix));

                if (ValidateEntry(_parcelIdControl, ADDRESS_CHARS) && invalidTypeIns == '') {
                    criteria = { searchLikeType: matchType, parcelId: _parcelIdControl.val(), doctype: docTypes, beginDate: locBeginDate, endDate: locEndDate, exclude: $('#excludeDocType_' + suffix).is(':checked'), ReturnIndexGroups: $('#indexgroup_' + suffix).is(':checked'), recordCount: $('#numberOfRecords-' + suffix).val(), townName: townName, mobileHomesOnly: mobileHomesOnly };
                }
                else {
                    if (invalidTypeIns == '') {
                        ThrowValidationError(_parcelIdControl, $('#parcelIdError'));
                    }
                    else { //One or more document types are invalid.
                        ThrowValidationError(_parcelIdControl, $('#docTypeTextError-' + suffix));
                    }
                    criteria = "NOGO";
                }
                break;
            case "RecordDateSearch":
                criteria = { beginDate: locBeginDate, endDate: locEndDate, exclude: $('#excludeDocType_' + suffix).is(':checked'), ReturnIndexGroups: $('#indexgroup_' + suffix).is(':checked'), recordCount: $('#numberOfRecords-' + suffix).val(), townName: townName, mobileHomesOnly: mobileHomesOnly };
                break;
            case "QuickSearch":
                //debugger;
                var _qsNameControl = $("#name-" + suffix);
                ClearValidationErrors(_qsNameControl, $('#nameError-' + suffix));

                if (ValidateEntry(_qsNameControl, NAME_CHARS)) {
                    criteria = { name: _qsNameControl.val(), doctype: docTypes, beginDate: locBeginDate, endDate: locEndDate, exclude: $('#excludeDocType_' + suffix).is(':checked'), ReturnIndexGroups: $('#indexgroup_' + suffix).is(':checked'), recordCount: $('#numberOfRecords-' + suffix).val(), townName: townName, mobileHomesOnly: mobileHomesOnly };
                }
                else {
                    ThrowValidationError(_qsNameControl, $('#nameError-' + suffix));
                    criteria = "NOGO";
                }
                break;
            case "AbstractSearch":
                criteria = {
                    beginDate: locBeginDate,
                    endDate: locEndDate,
                    doctype: docTypes,
                    recordCount: $('#numberOfRecords-' + suffix).val(),
                    exclude: $('#excludeDocType_' + suffix).is(':checked'),
                    ReturnIndexGroups: $('#indexgroup_' + suffix).is(':checked'),
                    townName: townName,
                    mobileHomesOnly: mobileHomesOnly,
                    abstractmasterrecording: $('#abstractalmasterrecordingsbutton.active').length > 0,
                    abstractallistings: $('#abstractallistinbutton.active').length > 0,
                    legalcode: $('#abstracttype').val(),
                    legalblock: $('#abstractblock').val(),
                    legalfromlot: $('#abstractfrom').val(),
                    legaltolot: $('#abstractto').val(),
                    legallookupid: $('#abstractlegallookupid').val()
                };
                break;
        }
    }

    criteria['g-recaptcha-response'] = $('.recaptchasection-' + suffix).find('[name="g-recaptcha-response"]').val();
    return criteria;
}

function GetDateValue(id) {
    var value = $('#' + id).val();
    if ((!value) || (value.replace(/^\s*|\s*$/, '').length == 0)) {
        value = null;
    }
    return value;
}

function GetResults(formName, url, criteria, captcha, captchaerror) {
    if (criteria == undefined) {
        console.assert(false, "Assert.  Criteria was undefined.")
        return; //common cause is timeout or other error.
    }

    if (url != 'GetMatchingNames') {
        $('#results, #resultsGridDiv').show();
        $('#backToDocuments #hideResults, #results-Print, #results-Export, #clearResults').hide();
        ScrollToTopOfSection($('#resultsTable'), 'slow');
    }
    $.ajax({
        url: "../Search/" + url,
        type: "POST",
        data: criteria,
        success: function (response) {
            if (typeof grecaptcha !== 'undefined') {
                grecaptcha.reset(captcha[0].captcha);
            }

            if (response.indexOf("Invalid Captcha") >= 0) {
                captchaerror.html("Invalid Captcha");
                captchaerror.show();
                return;
            }

            captchaerror.hide();

            if (url == 'GetMatchingNames') {
                $('#nameSearchModal>.modal-body').html(response);
            }
            else {
                $('#searchResults').html(response);
                $('#hideResults, #results-Print, #results-Export, #clearResults, #results, #resultsGridDiv').show();
            }

            $.post(site + 'Search/ShowCaptcha', function (result) {
                if (result == 'True')
                    captcha.show();
                else
                    captcha.hide();
            });
        },
        error: function (request, text, err) {
            $('#searchResults').html(''); alert("GetResults() - Unable to render search.\n" + err + text);
            $('#hideResults, #results-Print, #results-Export, #clearResults, #results, #resultsGridDiv').hide();
        }
    });
}

function ToggleSearchDetail() {
    if ($('#detailSection').is(":hidden") || splitView) {
        ShowDetailSection();
    }
    else {
        HideDetailSection();
    }
}

function ShowDetailSection() {
    if (!$('#bodySection').is(":hidden") && !splitView) {
        $('#bodySection').fadeOut(100);
    }
    if (Trim($('#detailSection').html()) == "") { // if the detail has not been retrieved yet
        GetDetailSection(0, 1, true);
    }
    else {
        $('#detailSection').fadeIn(150);
    }
    if (!splitView)
        ScrollToTopOfSection($('#detailSection'), 'fast');
}

function HideDetailSection() {
    $('#searchResults').show();
    $('#detailSection').fadeOut(100);
    $('#bodySection').fadeIn(150);
}

function UpdateDocumentTypeList(suffix) { //when category changes
    var currentText = $('#documentType-' + suffix).val(); //the contents before changes
    var docIds = $('#documentCategory-' + suffix).val();
    // update the text area
    $('#documentType-' + suffix).val('');
    // update the hidden field
    $('#documentTypeIds-' + suffix).val(docIds);
    $('[id^=dt-' + suffix + ']').removeAttr("checked");

    // update the check boxes
    if (Trim(docIds).length > 0) {
        var ids = docIds.split(",");
        var comma = "";
        for (var i = 0; i < ids.length; i++) {
            $('[id^=dt-' + suffix + ']').each(function () {
                if ($(this).val() == ids[i])
                    this.checked = !this.checked;
            });
            if (docTypeArray[ids[i]]) {
                var val = $('#documentType-' + suffix).val() + comma + docTypeArray[ids[i]].code;
                $('#documentType-' + suffix).val(val);
                comma = ",";
            }
        }
    }


    var newDocList = $('#documentType-' + suffix).val(); //the contents after changes
    if (currentText != '' && newDocList != '') {
        newDocList = currentText + "," + newDocList; //the new contents plus the prior contents
    }
    if (newDocList == '') {
        $('#documentTypeClear-' + suffix).addClass('hide');
    }
    else {
        $('#documentTypeClear-' + suffix).removeClass('hide');
    }

    $('#documentType-' + suffix).val(newDocList);
    ConvertCommaDelimitedStringToUniqueAndSorted($('#documentType-' + suffix));
}

function UpdateDocumentTypeListFromModal(suffix) {
    var newIds = '', newDocList = '', comma = "";
    var currentText = $('#documentType-' + suffix).val();
    // just get all selected. if list is different, rebuild document list and reset category to ""
    $('[id^=dt-' + suffix + ']:checked').each(function () {
        newIds += comma + $(this).val();
        newDocList += comma + docTypeArray[$(this).val()].code;
        comma = ",";
    });

    // update form inputs
    if ($('#documentTypeIds-' + suffix).val() != newIds) {
        $('#documentCategory-' + suffix).val('custom');
    }
    $('#documentTypeIds-' + suffix).val(newIds);

    // show the clear button if we have some values
    if (currentText != '' && newDocList != '') {
        newDocList = currentText + "," + newDocList;
    }
    if (newDocList == '') {
        $('#documentTypeClear-' + suffix).addClass('hide');
        $('#documentCategory-' + suffix).val('');
    }
    else {
        $('#documentTypeClear-' + suffix).removeClass('hide');
    }

    $('#documentType-' + suffix).val(newDocList);
    ConvertCommaDelimitedStringToUniqueAndSorted($('#documentType-' + suffix));


}

function ConvertCommaDelimitedStringToUniqueAndSorted(theControl) {
    //17148 - Cannot Do a Quick Search in Landmark
    if ($(theControl).length > 0) {
        var currentText = $(theControl).val();
        currentText = currentText.replace(/&amp;/g, '&');
        currentText = currentText.toUpperCase();
        var currentTextArray = currentText.split(",");
        currentTextArray = currentTextArray.unique();
        currentTextArray = currentTextArray.sort();
        currentText = currentTextArray.join(",");
        $(theControl).val(currentText);
    }
}

//http://www.devcurry.com/2010/04/remove-duplicate-elements-from-array.html
Array.prototype.unique = function () {
    var arrVal = this;
    var uniqueArr = [];
    for (var i = arrVal.length; i--;) {
        var val = arrVal[i];
        if ($.inArray(val, uniqueArr) === -1) {
            uniqueArr.unshift(val);
        }
    }
    return uniqueArr;
}


function ShowDocumentModal(item) {
    item.modal('show');
}

function ClearDocumentTypes(suffix) {
    $('#documentType-' + suffix + ',#documentCategory-' + suffix + ',#documentTypeIds-' + suffix).val('');
    $('#documentTypeClear-' + suffix).addClass('hide');
    $('[id^=dt-' + suffix + ']').removeAttr('checked');
}

$('#lot-searchdocinput,#subdivision-searchdocinput,#block-searchdocinput').change(function () {
    var lot = $('#lot-searchdocinput').val();
    var sub = $('#subdivision-searchdocinput').val();
    var block = "";

    var elemBlock = $('#block-searchdocinput');
    if (elemBlock.length != 0) {
        block = elemBlock.val();
    }

    if (lot != null && sub != null) {
        var ctrlpath = site + 'Search/LotStatus';
        $.post(ctrlpath, { lot: lot, subdivision: sub, block: block, time: new Date() }, function (data) {
            var redAlert = data.redAlert;

            if (data.lotStatus != null) {

                $('#lotStatusContainer').show();

                $('#lotstatus').html(data.lotStatus);

                if (redAlert == 'True') {
                    $('#lotStatusContainer').removeClass('alert-success')
                    $('#lotStatusContainer').addClass('alert-danger')
                }
                else {
                    $('#lotStatusContainer').removeClass('alert-danger')
                    $('#lotStatusContainer').addClass('alert-success')
                }
            }
            else {
                $('#lotstatus').html('');
                $('#lotStatusContainer').hide();
            }

        })
    }

});

function ToggleShowAllLegalFields() {
    var $icon = $('#showAllLegalFieldsIcon');
    var showAll = $icon.hasClass('icon-check-empty');
    var $checkbox = $('#results-showAllLegalFields');

    // Toggle icon classes and visibility of fields
    if (showAll) {
        $icon.removeClass('icon-check-empty').addClass('icon-check');
        $('#resultsTable th.legalSearchFieldCol, .legalfield').removeClass('hidden');
    } else {
        $icon.removeClass('icon-check').addClass('icon-check-empty');
        $('#resultsTable th.legalSearchFieldCol, .legalfield').addClass('hidden');
    }

    // Update aria-checked attribute based on the current state
    $checkbox.attr('aria-checked', showAll);

    // Persist the state
    SetSessionShowAllLegalFields(showAll);
    resizeGrid();
}

function resizeGrid() {

    if ($('#resultsTable_wrapper').width() >= $('#resultsGridDiv').width())
        $('#resultsGridDiv').width($('#resultsTable_wrapper').width() + 10);
    else {
        $('#resultsGridDiv').width('');
        $('#resultsGridDiv').width($('#resultsTable_wrapper').width() + 10);
    }

    $('.paginate_button.last').hide();
    $('#resultsHr').width($('#resultsGridDiv').width());

}

function SetSessionShowAllLegalFields(showAll) {
    $.ajax({
        url: site + "/Search/SetSessionShowAllLegalFields",
        type: "POST",
        data: { showAll: showAll, time: new Date() },
        error: function (request, text, err) { alert("Unable to set session legal field visibility.\n" + err + text); }
    });
}