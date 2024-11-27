window.addEventListener("load", (event) => {
    function applyFilters() {
        // Update URL
        if (window.history && window.history.replaceState) {
            var hashParts = [];
            if (showRedOnly.checked) {
                hashParts.push("show_red_only=1");
            }
            if (category.value) {
                hashParts.push("category=" + category.value);
            }
            if (search.value) {
                hashParts.push("search=" + encodeURIComponent(search.value));
            }

            window.history.replaceState({}, "", "#" + hashParts.join("&"));
        }

        var v = 0;
        // Table
        sites.querySelectorAll("tr.site").forEach(function (tr) {
            if (showRedOnly.checked && !tr.classList.contains("red")) {
                tr.style.display = "none";
                return;
            }
            if (category.value && !tr.classList.contains(category.value)) {
                tr.style.display = "none";
                return;
            }
            if (search.value && tr.dataset.domain.indexOf(search.value) == -1) {
                tr.style.display = "none";
                return;
            }

            tr.style.display = "";
            v += 1;
        });
        numVisible.innerText = v;

        // Events
        var totalShown = 0;
        document.querySelectorAll(".changes").forEach(function (div) {
            var shown = 0;
            div.querySelectorAll("li").forEach(function (li) {
                if (category.value && !li.classList.contains(category.value)) {
                    li.style.display = "none";
                    return;
                }

                if (search.value && li.dataset.domain.indexOf(search.value) == -1) {
                    li.style.display = "none";
                    return;
                }

                li.style.display = "";
                shown += 1;
            });
            div.style.display = shown > 0 ? "" : "none";
            totalShown += shown;
        });
        changesEmpty.style.display = totalShown == 0 ? "" : "none";
    }

    showRedOnly.addEventListener("change", applyFilters);
    category.addEventListener("change", applyFilters);
    // Wait 300ms after keyup events to let the user finish typing
    let applyFiltersTimer;
    search.addEventListener("keyup", function () {
        clearTimeout(applyFiltersTimer);
        applyFiltersTimer = setTimeout(applyFilters, 300);
    });

    // Apply filters from hash
    if (window.location.hash) {
        var params = {};
        var hashParts = window.location.hash.substring(1).split("&");
        for (pair of hashParts) {
            var nameValue = pair.split("=");
            params[nameValue[0]] = nameValue[1];
        }

        showRedOnly.checked = params.show_red_only == "1";
        category.value = params.category || "";
        search.value = params.search || "";
        applyFilters();
    }
});
