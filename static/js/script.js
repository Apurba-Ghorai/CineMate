

"use strict";



/* =========================================

   CINEMATE - PHASE 7

   Reviews, Watched, Profile, History,

   Trending and Upcoming

========================================= */



const API = {

    search: "/api/search",

    discover: "/api/discover",

    movie: "/api/movie/",

    recommendations: "/api/recommendations",

    watchlist: "/api/watchlist",

    watched: "/api/watched",

    reviews: "/api/reviews",

    profile: "/api/profile",

    recommendationHistory: "/api/recommendation-history",

    trending: "/api/movies/trending",

    upcoming: "/api/movies/upcoming",

    auth: {

        status: "/api/auth/status",

        register: "/api/auth/register",

        login: "/api/auth/login",

        logout: "/api/auth/logout"

    }

};



const $ = selector => document.querySelector(selector);



let watchlist = [];

let watchedMovies = [];

let currentUser = null;

let currentMovie = null;

let currentRecommendations = [];

let movieCache = new Map();

// Movies selected by the user for side-by-side comparison.
let comparisonMovies = new Map();



/* =========================================

   HELPERS

========================================= */



function escapeHTML(value = "") {

    return String(value).replace(/[&<>"']/g, char => ({

        "&": "&amp;",

        "<": "&lt;",

        ">": "&gt;",

        '"': "&quot;",

        "'": "&#039;"

    })[char]);

}



function safePoster(movie) {

    const poster = movie?.Poster || "";

    if (/^https?:\/\//i.test(poster) || poster.startsWith("/")) {

        return poster;

    }

    return "https://placehold.co/300x450/151515/ffffff?text=No+Poster";

}



function getMovieId(movie) {

    return movie?.imdbID || movie?.imdb_id || "";

}



function getMovieTitle(movie) {

    return movie?.Title || movie?.title || "Untitled Movie";

}



function rememberMovie(movie) {

    const id = getMovieId(movie);

    if (id) movieCache.set(id, movie);

}



function showMessage(element, message, error = false) {

    if (!element) return;

    element.textContent = message || "";

    element.style.color = error ? "#ff6879" : "";

}



async function fetchJSON(url, options = {}) {

    const response = await fetch(url, {

        credentials: "same-origin",

        ...options,

        headers: {

            "Content-Type": "application/json",

            ...(options.headers || {})

        }

    });



    const data = await response.json().catch(() => ({}));



    if (!response.ok) {

        throw new Error(data.error || "Something went wrong.");

    }



    return data;

}



function postJSON(url, data) {

    return fetchJSON(url, {

        method: "POST",

        body: JSON.stringify(data)

    });

}



function setLoading(element, message = "Loading...") {

    if (element) {

        element.innerHTML = `<div class="loading-state">${escapeHTML(message)}</div>`;

    }

}



/* =========================================

   MOVIE CARDS

========================================= */



function createMovieCard(movie, mode = "normal") {

    rememberMovie(movie);



    const id = getMovieId(movie);

    const title = getMovieTitle(movie);

    const year = movie.Year || "N/A";

    const poster = safePoster(movie);

    const rating = movie.imdbRating || "N/A";



    const saved = watchlist.some(m => getMovieId(m) === id);

    const watched = watchedMovies.some(m => getMovieId(m) === id);



    let extraButtons = "";



    if (id && currentUser) {

        extraButtons += `

            <button class="small-button ${watched ? "saved" : ""}"

                data-action="watched" data-id="${escapeHTML(id)}">

                ${watched ? "✓ Watched" : "✓ Watched"}

            </button>`;

    }



    return `

        <article class="movie-card">

            <img class="movie-poster"

                src="${escapeHTML(poster)}"

                alt="${escapeHTML(title)}"

                loading="lazy"

                data-action="details"

                data-id="${escapeHTML(id)}"

                onerror="this.src='https://placehold.co/300x450/151515/ffffff?text=No+Poster'">



            <div class="movie-info">

                <h3 class="movie-title"

                    data-action="details"

                    data-id="${escapeHTML(id)}">

                    ${escapeHTML(title)}

                </h3>



                <p class="movie-meta">${escapeHTML(year)}</p>



                <div class="movie-rating">★ ${escapeHTML(rating)}</div>



                <div class="movie-actions">

                    <button class="small-button"

                        data-action="details"

                        data-id="${escapeHTML(id)}">

                        Details

                    </button>



                    ${mode === "watchlist"

                        ? `<button class="small-button"

                            data-action="remove-watchlist"

                            data-id="${escapeHTML(id)}">Remove</button>`

                        : `<button class="small-button ${saved ? "saved" : ""}"

                            data-action="watchlist"

                            data-id="${escapeHTML(id)}">

                            ${saved ? "♥ Saved" : "+ My List"}

                          </button>`

                    }

                </div>



                ${extraButtons}

            </div>

        </article>`;

}



function renderMovies(element, movies, mode = "normal") {

    if (!element) return;



    if (!movies?.length) {

        element.innerHTML = `<div class="empty-state">No movies found.</div>`;

        return;

    }



    element.innerHTML = movies.map(movie =>

        createMovieCard(movie, mode)

    ).join("");

}



function renderCurrentCards() {

    renderMovies($("#watchlistMovies"), watchlist, "watchlist");

    renderMovies($("#watchedMovies"), watchedMovies, "normal");

    updateWatchlistCount();

}



function updateWatchlistCount() {

    const count = $("#watchlistCount");

    const total = $("#watchlistTotal");



    if (count) count.textContent = watchlist.length;

    if (total) total.textContent = `${watchlist.length} MOVIES`;

}



/* =========================================

   WATCHLIST

========================================= */



async function loadWatchlist() {

    if (!currentUser) {

        watchlist = [];

        renderCurrentCards();

        return;

    }



    try {

        const data = await fetchJSON(API.watchlist);

        watchlist = data.movies || [];

        renderCurrentCards();

    } catch (error) {

        console.error(error);

        showMessage($("#watchlistMessage"), error.message, true);

    }

}



async function addToWatchlist(movie) {

    if (!currentUser) {

        openAuthModal();

        return;

    }



    try {

        const data = await postJSON(API.watchlist, { movie });

        showMessage($("#watchlistMessage"), data.message);

        await loadWatchlist();

    } catch (error) {

        showMessage($("#watchlistMessage"), error.message, true);

    }

}



async function removeFromWatchlist(id) {

    try {

        await fetchJSON(`${API.watchlist}/${encodeURIComponent(id)}`, {

            method: "DELETE"

        });

        await loadWatchlist();

    } catch (error) {

        alert(error.message);

    }

}



/* =========================================

   WATCHED HISTORY

========================================= */



async function loadWatchedHistory() {

    const container = $("#watchedMovies");



    if (!currentUser) {

        watchedMovies = [];

        renderMovies(container, []);

        return;

    }



    try {

        const data = await fetchJSON(API.watched);

        watchedMovies = data.movies || [];

        renderMovies(container, watchedMovies);

    } catch (error) {

        showMessage($("#watchedMessage"), error.message, true);

    }

}



async function markAsWatched(movie) {

    if (!currentUser) {

        openAuthModal();

        return;

    }



    try {

        const data = await postJSON(API.watched, { movie });

        showMessage($("#watchedMessage"), data.message);

        await loadWatchedHistory();

    } catch (error) {

        alert(error.message);

    }

}



async function removeWatched(id) {

    try {

        await fetchJSON(`${API.watched}/${encodeURIComponent(id)}`, {

            method: "DELETE"

        });

        await loadWatchedHistory();

    } catch (error) {

        alert(error.message);

    }

}



/* =========================================

   SEARCH

========================================= */



async function searchMovies(query) {

    const results = $("#searchResults");

    const message = $("#searchMessage");



    setLoading(results, "Searching movies...");



    try {

        const data = await fetchJSON(

            `${API.search}?q=${encodeURIComponent(query)}`

        );



        renderMovies(results, data.movies || []);

        showMessage(message, `${data.totalResults || 0} movies found.`);

    } catch (error) {

        results.innerHTML = "";

        showMessage(message, error.message, true);

    }

}



$("#searchForm")?.addEventListener("submit", event => {

    event.preventDefault();



    const query = $("#searchInput")?.value.trim();

    if (query) searchMovies(query);

});



$("#navSearchButton")?.addEventListener("click", () => {

    $("#search")?.scrollIntoView({ behavior: "smooth" });

    $("#searchInput")?.focus();

});



/* =========================================

   DISCOVER COLLECTIONS

========================================= */



async function loadDiscoverCollections() {

    const container = $("#collectionsContainer");

    setLoading(container, "Loading movie collections...");



    try {

        const data = await fetchJSON(API.discover);

        container.innerHTML = "";



        for (const [name, movies] of Object.entries(data.collections || {})) {

            if (!movies?.length) continue;



            const section = document.createElement("div");

            section.className = "collection-row";



            section.innerHTML = `

                <h3 class="collection-title">

                    ${escapeHTML(name.replaceAll("-", " ").toUpperCase())}

                </h3>

                <div class="collection-movies"></div>

            `;



            container.appendChild(section);

            renderMovies(section.querySelector(".collection-movies"), movies);

        }

    } catch (error) {

        showMessage($("#discoverMessage"), error.message, true);

    }

}



/* =========================================

   RECOMMENDATIONS

========================================= */



async function generateRecommendations() {

    const genres = [...document.querySelectorAll(

        "#genreOptions input:checked"

    )].map(input => input.value);



    const language = $("#languageSelect")?.value || "";

    const results = $("#recommendationResults");



    setLoading(results, "Finding movies for you...");



    try {

        const data = await postJSON(API.recommendations, {

            genres,

            language,

            watchlist: watchlist.map(movie => ({

                imdbID: getMovieId(movie)

            }))

        });



        currentRecommendations = data.recommendations || [];



        renderMovies(results, currentRecommendations);



        showMessage(

            $("#recommendationMessage"),

            `${currentRecommendations.length} recommendations found.`

        );



        // Save this recommendation session for the signed-in user.
        if (currentUser && currentRecommendations.length) {
            try {
                await postJSON(API.recommendationHistory, {
                    preferences: { genres, language },
                    recommendations: currentRecommendations
                });
                await loadRecommendationHistory();
            } catch (historyError) {
                console.error("Could not save recommendation history:", historyError);
                showMessage(
                    $("#recommendationMessage"),
                    `${currentRecommendations.length} recommendations found, but history could not be saved.`
                );
            }
        }

    } catch (error) {

        results.innerHTML = "";

        showMessage($("#recommendationMessage"), error.message, true);

    }

}



$("#recommendButton")?.addEventListener(

    "click",

    generateRecommendations

);



/* =========================================

   TRENDING AND UPCOMING

========================================= */



async function loadMovieSection(url, containerId) {

    const container = $(containerId);

    if (!container) return;



    setLoading(container);



    try {

        const data = await fetchJSON(url);

        renderMovies(container, data.movies || []);

    } catch (error) {

        container.innerHTML =

            `<div class="empty-state">${escapeHTML(error.message)}</div>`;

    }

}



/* =========================================

   MOVIE DETAILS AND REVIEWS

========================================= */



async function openMovieDetails(id) {

    if (!id) return;



    const modal = $("#movieModal");

    const content = $("#movieDetailsContent");



    modal?.classList.add("show");

    modal?.setAttribute("aria-hidden", "false");



    document.body.style.overflow = "hidden";

    setLoading(content, "Loading movie details...");



    try {

        const data = await fetchJSON(

            `${API.movie}${encodeURIComponent(id)}`

        );



        currentMovie = data.movie;

        rememberMovie(currentMovie);



        renderMovieDetails(currentMovie);

        await loadReviews(id);

    } catch (error) {

        content.innerHTML =

            `<div class="empty-state">${escapeHTML(error.message)}</div>`;

    }

}



function renderMovieDetails(movie) {

    const content = $("#movieDetailsContent");

    const id = getMovieId(movie);



    content.innerHTML = `

        <div class="details-layout">

            <img class="details-poster"

                src="${escapeHTML(safePoster(movie))}"

                alt="${escapeHTML(getMovieTitle(movie))}">



            <div class="details-content">

                <h2 id="modalTitle">${escapeHTML(getMovieTitle(movie))}</h2>



                <div class="details-facts">

                    <span>${escapeHTML(movie.Year || "N/A")}</span>

                    <span>★ ${escapeHTML(movie.imdbRating || "N/A")}</span>

                    <span>${escapeHTML(movie.Runtime || "N/A")}</span>

                </div>



                <p>${escapeHTML(movie.Plot || "No plot available.")}</p>



                <div class="details-label">GENRE</div>

                <p>${escapeHTML(movie.Genre || "N/A")}</p>



                <div class="details-label">DIRECTOR</div>

                <p>${escapeHTML(movie.Director || "N/A")}</p>



                <div class="details-label">CAST</div>

                <p>${escapeHTML(movie.Actors || "N/A")}</p>



                <div class="details-facts">

                    <button class="primary-button"

                        data-action="watchlist"

                        data-id="${escapeHTML(id)}">

                        ♥ Add to Watchlist

                    </button>



                    ${currentUser ? `

                        <button class="secondary-button"

                            data-action="watched"

                            data-id="${escapeHTML(id)}">

                            Mark as Watched

                        </button>` : ""}

                </div>

            </div>

        </div>



        <section class="review-section">

            <div class="section-heading">

                <div>

                    <span class="section-kicker">COMMUNITY OPINIONS</span>

                    <h2>Reviews & <span>Ratings</span></h2>

                </div>

                <span id="reviewAverage" class="section-tag">No ratings yet</span>

            </div>



            <form id="reviewForm" class="review-form">

                <label class="preference-label">YOUR RATING (1–10)</label>



                <select id="reviewRating" required>

                    ${Array.from({length: 10}, (_, i) =>

                        `<option value="${i + 1}" ${i === 9 ? "selected" : ""}>

                            ${i + 1} / 10

                        </option>`

                    ).join("")}

                </select>



                <label class="preference-label">YOUR REVIEW</label>



                <textarea id="reviewText"

                    maxlength="2000"

                    rows="4"

                    placeholder="Share your thoughts about this movie..."></textarea>



                <button class="primary-button" type="submit">

                    Submit Review

                </button>

            </form>



            <div id="reviewMessage" class="message"></div>

            <div id="reviewsList"></div>

        </section>

    `;



    $("#reviewForm")?.addEventListener("submit", submitReview);

}



async function loadReviews(id) {

    try {

        const data = await fetchJSON(

            `${API.reviews}/${encodeURIComponent(id)}`

        );



        const average = $("#reviewAverage");

        if (average) {

            average.textContent = data.total

                ? `★ ${data.average_rating}/10 · ${data.total} reviews`

                : "No ratings yet";

        }



        const list = $("#reviewsList");

        if (!list) return;



        if (!data.reviews?.length) {

            list.innerHTML = `<div class="empty-state">No reviews yet. Be the first!</div>`;

            return;

        }



        list.innerHTML = data.reviews.map(review => `

            <article class="review-card">

                <div class="review-card-heading">

                    <strong>${escapeHTML(review.user_name)}</strong>

                    <span>★ ${escapeHTML(review.rating)}/10</span>

                </div>

                <p>${escapeHTML(review.review || "No written review.")}</p>

                <small>${escapeHTML(review.updated_at || "")}</small>

            </article>

        `).join("");

    } catch (error) {

        showMessage($("#reviewMessage"), error.message, true);

    }

}



async function submitReview(event) {

    event.preventDefault();



    if (!currentUser) {

        openAuthModal();

        return;

    }



    if (!currentMovie) return;



    const review = $("#reviewText").value.trim();

    const rating = Number($("#reviewRating").value);



    try {

        const data = await postJSON(API.reviews, {

            imdb_id: getMovieId(currentMovie),

            movie_title: getMovieTitle(currentMovie),

            rating,

            review

        });



        showMessage($("#reviewMessage"), data.message);

        $("#reviewText").value = "";



        await loadReviews(getMovieId(currentMovie));

    } catch (error) {

        showMessage($("#reviewMessage"), error.message, true);

    }

}



/* =========================================

   PROFILE MANAGEMENT

========================================= */



function createProfileModal() {

    if ($("#profileModal")) return;



    document.body.insertAdjacentHTML("beforeend", `

        <div class="feature-overlay" id="profileModal" hidden>

            <div class="feature-modal">

                <button class="feature-close" type="button" data-close="profileModal" aria-label="Close profile">×</button>



                <span class="section-kicker">YOUR ACCOUNT</span>

                <h2>Manage <span>Profile</span></h2>



                <form id="profileForm" class="feature-form">

                    <label>Full Name</label>

                    <input id="profileName" maxlength="80" required>



                    <label>Email Address</label>

                    <input id="profileEmail" type="email" maxlength="254" required>



                    <label>Current Password</label>

                    <input id="profileCurrentPassword" type="password" required>



                    <label>New Password (optional)</label>

                    <input id="profileNewPassword" type="password"

                        minlength="8" maxlength="128"

                        placeholder="Leave blank to keep current password">



                    <button class="primary-button" type="submit">

                        Save Changes

                    </button>

                </form>



                <div id="profileMessage" class="message"></div>

            </div>

        </div>

    `);



    $("#profileForm").addEventListener("submit", updateProfile);

}



async function openProfile() {

    if (!currentUser) {

        openAuthModal();

        return;

    }



    createProfileModal();



    const modal = $("#profileModal");

    if (!modal) return;

    // Clear a previous inline display:none so the modal can reopen.
    modal.hidden = false;
    modal.style.removeProperty("display");



    try {

        const data = await fetchJSON(API.profile);

        $("#profileName").value = data.user.name || "";

        $("#profileEmail").value = data.user.email || "";

        $("#profileCurrentPassword").value = "";

        $("#profileNewPassword").value = "";

    } catch (error) {

        showMessage($("#profileMessage"), error.message, true);

    }

}



async function updateProfile(event) {

    event.preventDefault();



    try {

        const data = await fetchJSON(API.profile, {

            method: "PUT",

            body: JSON.stringify({

                name: $("#profileName").value.trim(),

                email: $("#profileEmail").value.trim(),

                current_password: $("#profileCurrentPassword").value,

                new_password: $("#profileNewPassword").value

            })

        });



        currentUser = data.user;

        updateAccountUI();

        showMessage($("#profileMessage"), data.message);



        $("#profileCurrentPassword").value = "";

        $("#profileNewPassword").value = "";

    } catch (error) {

        showMessage($("#profileMessage"), error.message, true);

    }

}



/* =========================================

   RECOMMENDATION HISTORY

========================================= */



async function loadRecommendationHistory() {

    const container = $("#recommendationHistory");

    if (!container) return;



    if (!currentUser) {

        container.innerHTML =

            `<div class="empty-state">Sign in to view your recommendation history.</div>`;

        return;

    }



    setLoading(container, "Loading your previous recommendations...");



    try {

        const data = await fetchJSON(API.recommendationHistory);

        const history = data.history || [];



        if (!history.length) {

            container.innerHTML =

                `<div class="empty-state">No recommendation history yet.</div>`;

            return;

        }



        container.innerHTML = history.map(item => `

            <article class="history-card">

                <div class="history-heading">

                    <div>

                        <strong>${escapeHTML(

                            (item.preferences?.genres || []).join(", ") || "All Genres"

                        )}</strong>

                        <p>${escapeHTML(item.preferences?.language || "Any language")}</p>

                        <small>${escapeHTML(item.created_at)}</small>

                    </div>



                    <button class="small-button"

                        data-action="delete-history"

                        data-id="${Number(item.id)}">

                        Delete

                    </button>

                </div>



                <div class="history-movies">

                    ${(item.recommendations || []).map(movie => `

                        <button class="history-movie"

                            data-action="details"

                            data-id="${escapeHTML(getMovieId(movie))}">

                            <img src="${escapeHTML(safePoster(movie))}"

                                alt="${escapeHTML(getMovieTitle(movie))}">

                            <span>${escapeHTML(getMovieTitle(movie))}</span>

                        </button>

                    `).join("")}

                </div>

            </article>

        `).join("");



        history.forEach(item => {

            (item.recommendations || []).forEach(rememberMovie);

        });

    } catch (error) {

        container.innerHTML =

            `<div class="empty-state">${escapeHTML(error.message)}</div>`;

    }

}



async function deleteRecommendationHistory(id) {

    try {

        await fetchJSON(`${API.recommendationHistory}/${id}`, {

            method: "DELETE"

        });

        await loadRecommendationHistory();

    } catch (error) {

        alert(error.message);

    }

}



async function clearRecommendationHistory() {

    if (!confirm("Clear all your recommendation history?")) return;



    try {

        await fetchJSON(API.recommendationHistory, {

            method: "DELETE"

        });

        await loadRecommendationHistory();

    } catch (error) {

        alert(error.message);

    }

}



/* =========================================

   MOVIE COMPARISON

========================================= */

async function searchComparisonMovies(query) {
    const results = $("#comparisonSearchResults");
    if (!results) return;

    if (!query || query.trim().length < 2) {
        results.innerHTML = `<div class="empty-state">Enter at least 2 characters to search.</div>`;
        return;
    }

    setLoading(results, "Searching movies...");

    try {
        const data = await fetchJSON(`${API.search}?q=${encodeURIComponent(query.trim())}`);
        const movies = data.movies || [];

        if (!movies.length) {
            results.innerHTML = `<div class="empty-state">No matching movies found.</div>`;
            return;
        }

        movies.slice(0, 12).forEach(rememberMovie);
        results.innerHTML = movies.slice(0, 12).map(movie => {
            const id = getMovieId(movie);
            const alreadyAdded = comparisonMovies.has(id);
            return `
                <article class="compare-search-card">
                    <img src="${escapeHTML(safePoster(movie))}" alt="${escapeHTML(getMovieTitle(movie))}">
                    <div class="compare-search-info">
                        <strong>${escapeHTML(getMovieTitle(movie))}</strong>
                        <span>${escapeHTML(movie.Year || "Year unavailable")}</span>
                    </div>
                    <button type="button" class="small-button" data-action="compare-add" data-id="${escapeHTML(id)}" ${alreadyAdded ? "disabled" : ""}>
                        ${alreadyAdded ? "Added" : "Add"}
                    </button>
                </article>
            `;
        }).join("");
    } catch (error) {
        results.innerHTML = `<div class="empty-state">${escapeHTML(error.message)}</div>`;
    }
}

function addMovieToComparison(id) {
    const movie = movieCache.get(id);
    if (!movie || !id) return;

    if (comparisonMovies.has(id)) return;
    if (comparisonMovies.size >= 4) {
        showMessage($("#comparisonMessage"), "You can compare a maximum of 4 movies.", true);
        return;
    }

    comparisonMovies.set(id, movie);
    showMessage($("#comparisonMessage"), "Movie added to comparison.");
    renderComparisonSelection();

    // Update Add buttons in the current search results.
    document.querySelectorAll(`#comparisonSearchResults [data-action="compare-add"][data-id="${CSS.escape(id)}"]`).forEach(button => {
        button.disabled = true;
        button.textContent = "Added";
    });
}

function removeMovieFromComparison(id) {
    comparisonMovies.delete(id);
    renderComparisonSelection();
    document.querySelectorAll(`#comparisonSearchResults [data-action="compare-add"][data-id="${CSS.escape(id)}"]`).forEach(button => {
        button.disabled = false;
        button.textContent = "Add";
    });
}

function renderComparisonSelection() {
    const container = $("#comparisonSelected");
    if (!container) return;

    const count = $("#comparisonCount");
    if (count) count.textContent = `(${comparisonMovies.size}/4)`;

    if (!comparisonMovies.size) {
        container.innerHTML = `<div class="empty-state">No movies selected. Search and add at least 2 movies.</div>`;
        $("#compareNowButton")?.setAttribute("disabled", "disabled");
        $("#comparisonTableWrap")?.replaceChildren();
        return;
    }

    container.innerHTML = [...comparisonMovies.entries()].map(([id, movie]) => `
        <article class="compare-selected-card">
            <img src="${escapeHTML(safePoster(movie))}" alt="${escapeHTML(getMovieTitle(movie))}">
            <div class="compare-selected-info">
                <strong>${escapeHTML(getMovieTitle(movie))}</strong>
                <span>${escapeHTML(movie.Year || "N/A")}</span>
            </div>
            <button type="button" class="compare-remove-button" data-action="compare-remove" data-id="${escapeHTML(id)}" aria-label="Remove ${escapeHTML(getMovieTitle(movie))}">×</button>
        </article>
    `).join("");

    const compareButton = $("#compareNowButton");
    if (compareButton) compareButton.disabled = comparisonMovies.size < 2;
}

function comparisonValue(movie, field) {
    const value = movie?.[field];
    return value && value !== "N/A" ? String(value) : "Not available";
}

async function compareSelectedMovies() {
    const tableWrap = $("#comparisonTableWrap");
    if (!tableWrap) return;

    if (comparisonMovies.size < 2) {
        showMessage($("#comparisonMessage"), "Select at least 2 movies to compare.", true);
        return;
    }

    setLoading(tableWrap, "Loading movie details for comparison...");

    try {
        const selected = [...comparisonMovies.entries()];
        const detailedMovies = await Promise.all(selected.map(async ([id, cachedMovie]) => {
            try {
                const data = await fetchJSON(`${API.movie}${encodeURIComponent(id)}`);
                const movie = data.movie || cachedMovie;
                rememberMovie(movie);
                comparisonMovies.set(id, movie);
                return movie;
            } catch (error) {
                return cachedMovie;
            }
        }));

        const fields = [
            ["Release year", "Year"],
            ["IMDb rating", "imdbRating"],
            ["Genre", "Genre"],
            ["Runtime", "Runtime"],
            ["Language", "Language"],
            ["Director", "Director"],
            ["Cast", "Actors"],
            ["Country", "Country"],
            ["Plot", "Plot"]
        ];

        const headerCells = detailedMovies.map(movie => `
            <th class="compare-movie-heading">
                <img src="${escapeHTML(safePoster(movie))}" alt="${escapeHTML(getMovieTitle(movie))}">
                <strong>${escapeHTML(getMovieTitle(movie))}</strong>
            </th>
        `).join("");

        const rows = fields.map(([label, field]) => `
            <tr>
                <th scope="row">${escapeHTML(label)}</th>
                ${detailedMovies.map(movie => `<td>${escapeHTML(comparisonValue(movie, field))}</td>`).join("")}
            </tr>
        `).join("");

        tableWrap.innerHTML = `
            <div class="comparison-table-scroll">
                <table class="comparison-table">
                    <thead><tr><th>Movie details</th>${headerCells}</tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
        showMessage($("#comparisonMessage"), `Comparing ${detailedMovies.length} movies.`);
    } catch (error) {
        tableWrap.innerHTML = `<div class="empty-state">${escapeHTML(error.message)}</div>`;
    }
}

function bindComparisonControls() {
    const form = $("#comparisonSearchForm");
    if (form && !form.dataset.bound) {
        form.dataset.bound = "true";
        form.addEventListener("submit", event => {
            event.preventDefault();
            searchComparisonMovies($("#comparisonSearchInput")?.value || "");
        });
    }

    const compareButton = $("#compareNowButton");
    if (compareButton && !compareButton.dataset.bound) {
        compareButton.dataset.bound = "true";
        compareButton.addEventListener("click", compareSelectedMovies);
    }
}


/* =========================================

   AUTHENTICATION

========================================= */



function openAuthModal() {

    const modal = $("#authModal");

    if (!modal) return;



    modal.hidden = false;

    modal.classList.add("show");

    modal.setAttribute("aria-hidden", "false");

}



function closeAuthModal() {

    const modal = $("#authModal");

    if (!modal) return;



    modal.hidden = true;

    modal.classList.remove("show");

    modal.setAttribute("aria-hidden", "true");

}



function switchAuth(mode) {

    const login = mode === "login";



    $("#authLoginForm").hidden = !login;

    $("#authRegisterForm").hidden = login;



    $("#loginTab").classList.toggle("active", login);

    $("#registerTab").classList.toggle("active", !login);



    $("#authTitle").innerHTML = login

        ? 'Welcome <span>back.</span>'

        : 'Create your <span>account.</span>';



    $("#authDescription").textContent = login

        ? "Sign in to continue exploring your movie universe."

        : "Join CineMate and build your personal movie collection.";



    showMessage($("#authMessage"), "");

}



$("#accountButton")?.addEventListener("click", openAuthModal);

$("#closeAuthModal")?.addEventListener("click", closeAuthModal);



$("#authModal")?.addEventListener("click", event => {

    if (event.target.id === "authModal") closeAuthModal();

});



$("#loginTab")?.addEventListener("click", () => switchAuth("login"));

$("#registerTab")?.addEventListener("click", () => switchAuth("register"));



document.querySelectorAll("[data-switch-auth]").forEach(button => {

    button.addEventListener("click", () => {

        switchAuth(button.dataset.switchAuth);

    });

});



$("#authLoginForm")?.addEventListener("submit", async event => {

    event.preventDefault();



    try {

        const data = await postJSON(API.auth.login, {

            email: $("#loginEmail").value.trim(),

            password: $("#loginPassword").value

        });



        currentUser = data.user;

        closeAuthModal();

        updateAccountUI();

        await refreshUserData();

    } catch (error) {

        showMessage($("#authMessage"), error.message, true);

    }

});



$("#authRegisterForm")?.addEventListener("submit", async event => {

    event.preventDefault();



    try {

        const data = await postJSON(API.auth.register, {

            name: $("#registerName").value.trim(),

            email: $("#registerEmail").value.trim(),

            password: $("#registerPassword").value

        });



        currentUser = data.user;

        closeAuthModal();

        updateAccountUI();

        await refreshUserData();

    } catch (error) {

        showMessage($("#authMessage"), error.message, true);

    }

});



async function logout() {

    try {

        await postJSON(API.auth.logout, {});



        currentUser = null;

        watchlist = [];

        watchedMovies = [];



        updateAccountUI();

        renderCurrentCards();



        await loadRecommendationHistory();

    } catch (error) {

        alert(error.message);

    }

}



$("#logoutButton")?.addEventListener("click", logout);



function updateAccountUI() {

    const guestButton = $("#accountButton");

    const userAccount = $("#userAccount");



    if (currentUser) {

        if (guestButton) guestButton.hidden = true;

        if (userAccount) userAccount.hidden = false;



        $("#loggedInName").textContent = currentUser.name || "User";

        $("#userAvatar").textContent =

            (currentUser.name || "U").charAt(0).toUpperCase();

    } else {

        if (guestButton) guestButton.hidden = false;

        if (userAccount) userAccount.hidden = true;

    }

}



async function checkAuthStatus() {

    try {

        const data = await fetchJSON(API.auth.status);

        currentUser = data.logged_in ? data.user : null;

        updateAccountUI();



        if (currentUser) await refreshUserData();

    } catch (error) {

        console.error("Authentication status:", error);

    }

}



async function refreshUserData() {

    await Promise.all([

        loadWatchlist(),

        loadWatchedHistory(),

        loadRecommendationHistory()

    ]);

}



/* =========================================

   DYNAMIC PHASE 7 SECTIONS

========================================= */



function createFeatureSections() {

    const watchlistSection = $("#watchlist");



    if (!watchlistSection) return;



    if (!$("#watched")) {

        watchlistSection.insertAdjacentHTML("afterend", `

            <section class="content-section" id="watched">

                <div class="section-heading">

                    <div>

                        <span class="section-kicker">YOUR MOVIE JOURNEY</span>

                        <h2>Watched <span>movies.</span></h2>

                        <p class="section-description">

                            Movies you have already enjoyed.

                        </p>

                    </div>

                </div>

                <div id="watchedMessage" class="message"></div>

                <div id="watchedMovies" class="movie-grid"></div>

            </section>

        `);

    }



    if (!$("#trending")) {

        $("#watched").insertAdjacentHTML("afterend", `

            <section class="content-section" id="trending">

                <div class="section-heading">

                    <div>

                        <span class="section-kicker">POPULAR RIGHT NOW</span>

                        <h2>Trending <span>movies.</span></h2>

                    </div>

                </div>

                <div id="trendingMovies" class="movie-grid"></div>

            </section>

        `);

    }



    if (!$("#upcoming")) {

        $("#trending").insertAdjacentHTML("afterend", `

            <section class="content-section" id="upcoming">

                <div class="section-heading">

                    <div>

                        <span class="section-kicker">WHAT PEOPLE ARE ANTICIPATING</span>

                        <h2>Upcoming <span>picks.</span></h2>

                        <p class="section-description">

                            Popular anticipated movies. Release dates may vary.

                        </p>

                    </div>

                </div>

                <div id="upcomingMovies" class="movie-grid"></div>

            </section>

        `);

    }



    if (!$("#recommendationHistorySection")) {

        $("#upcoming").insertAdjacentHTML("afterend", `

            <section class="content-section" id="recommendationHistorySection">

                <div class="section-heading">

                    <div>

                        <span class="section-kicker">YOUR PERSONALIZED JOURNEY</span>

                        <h2>Recommendation <span>history.</span></h2>

                        <p class="section-description">

                            Revisit your previous movie recommendations.

                        </p>

                    </div>



                    <button class="secondary-button"

                        id="clearRecommendationHistory">

                        Clear History

                    </button>

                </div>



                <div id="recommendationHistory"></div>

            </section>

        `);



        $("#clearRecommendationHistory").addEventListener(

            "click",

            clearRecommendationHistory

        );

    }



    if (!$("#comparisonSection")) {
        $("#recommendationHistorySection").insertAdjacentHTML("afterend", `
            <section class="content-section" id="comparisonSection">
                <div class="section-heading">
                    <div>
                        <span class="section-kicker">MAKE THE RIGHT PICK</span>
                        <h2>Movie <span>comparison.</span></h2>
                        <p class="section-description">Compare 2 to 4 movies side by side before choosing what to watch.</p>
                    </div>
                </div>

                <form id="comparisonSearchForm" class="comparison-search-form">
                    <input id="comparisonSearchInput" type="search" placeholder="Search a movie title..." autocomplete="off" required>
                    <button type="submit" class="primary-button">Search movies</button>
                </form>
                <div id="comparisonMessage" class="message" aria-live="polite"></div>
                <div id="comparisonSearchResults" class="comparison-search-results"></div>

                <div class="comparison-selection-heading">
                    <h3>Selected movies <span id="comparisonCount">(0/4)</span></h3>
                    <button type="button" class="secondary-button" id="compareNowButton" disabled>Compare movies</button>
                </div>
                <div id="comparisonSelected" class="comparison-selected-grid">
                    <div class="empty-state">No movies selected. Search and add at least 2 movies.</div>
                </div>
                <div id="comparisonTableWrap"></div>
            </section>
        `);
        bindComparisonControls();
    }

    const nav = document.querySelector(".nav-links");



    if (nav && !nav.querySelector('[href="#watched"]')) {

        nav.insertAdjacentHTML("beforeend", `

            <a href="#watched" class="nav-link">Watched</a>

            <a href="#trending" class="nav-link">Trending</a>

        `);

    }

    if (nav && !nav.querySelector('[href="#comparisonSection"]')) {
        nav.insertAdjacentHTML("beforeend", `<a href="#comparisonSection" class="nav-link">Compare</a>`);
    }

    bindComparisonControls();
    renderComparisonSelection();

    const accountArea = $("#accountArea");



    if (accountArea && !$("#profileButton")) {

        accountArea.insertAdjacentHTML("beforeend", `

            <button id="profileButton" class="logout-button" type="button">

                Profile

            </button>

        `);



        $("#profileButton").addEventListener("click", openProfile);

    }



    createProfileModal();

    const profileModal = $("#profileModal");
    if (profileModal && !profileModal.dataset.backdropBound) {
        profileModal.dataset.backdropBound = "true";
        profileModal.addEventListener("click", event => {
            if (event.target === profileModal) {
                profileModal.hidden = true;
                profileModal.style.display = "none";
            }
        });
    }
}



/* =========================================

   GLOBAL EVENT DELEGATION

========================================= */



document.addEventListener("click", async event => {
    // Check close buttons first. The old handler returned early before
    // reaching data-close, so the Profile X button could not work.
    const closeButton = event.target.closest("[data-close]");

    if (closeButton) {
        event.preventDefault();
        const modalId = closeButton.dataset.close;
        const modal = document.getElementById(modalId);

        if (modal) {
            modal.hidden = true;
            modal.style.display = "none";
        }

        if (modalId === "movieModal") {
            document.body.style.overflow = "";
            currentMovie = null;
        }
        return;
    }

    const button = event.target.closest("[data-action]");
    if (!button) return;

    const action = button.dataset.action;
    const id = button.dataset.id;
    const movie = movieCache.get(id);

    if (action === "details") {
        await openMovieDetails(id);
    } else if (action === "watchlist" && movie) {
        await addToWatchlist(movie);
    } else if (action === "remove-watchlist") {
        await removeFromWatchlist(id);
    } else if (action === "watched" && movie) {
        await markAsWatched(movie);
    } else if (action === "delete-history") {
        await deleteRecommendationHistory(Number(id));
    } else if (action === "remove-watched") {
        await removeWatched(id);
    } else if (action === "compare-add") {
        addMovieToComparison(id);
    } else if (action === "compare-remove") {
        removeMovieFromComparison(id);
    }
});



/* =========================================

   MOVIE MODAL CONTROLS

========================================= */



function closeMovieModal() {

    $("#movieModal")?.classList.remove("show");

    $("#movieModal")?.setAttribute("aria-hidden", "true");

    document.body.style.overflow = "";

    currentMovie = null;

}



$("#closeModal")?.addEventListener("click", closeMovieModal);



$("#movieModal")?.addEventListener("click", event => {

    if (event.target.id === "movieModal") closeMovieModal();

});



document.addEventListener("keydown", event => {

    if (event.key === "Escape") {

        closeMovieModal();

        closeAuthModal();



        const profile = $("#profileModal");

        if (profile) {
            profile.hidden = true;
            profile.style.display = "none";
        }

    }

});



/* =========================================

   INITIALIZATION

========================================= */



async function initializeCineMate() {

    createFeatureSections();



    await checkAuthStatus();



    await Promise.all([

        loadDiscoverCollections(),

        loadMovieSection(API.trending, "#trendingMovies"),

        loadMovieSection(API.upcoming, "#upcomingMovies")

    ]);

}



document.addEventListener("DOMContentLoaded", initializeCineMate);
