let currentThreadId = localStorage.getItem("travel_thread_id") || null;
let latestAnswerMarkdown = "";
let loadingTimer = null;
const loadingMessages = [
    "Understanding your trip...",
    "Searching for flights...",
    "Finding hotels...",
    "Building your itinerary...",
    "Finalizing your travel plan..."
];

function setPrompt(text) {
    document.getElementById("userInput").value = text;
}

function setLoading(isLoading) {
    const sendBtn = document.getElementById("sendBtn");
    const btnText = document.getElementById("btnText");
    const btnLoader = document.getElementById("btnLoader");

    sendBtn.disabled = isLoading;
    sendBtn.setAttribute("aria-busy", String(isLoading));

    if (isLoading) {
        btnText.classList.add("hidden");
        btnLoader.classList.remove("hidden");
        let messageIndex = 0;
        document.getElementById("loadingText").textContent = loadingMessages[messageIndex];
        loadingTimer = setInterval(() => {
            messageIndex = Math.min(messageIndex + 1, loadingMessages.length - 1);
            document.getElementById("loadingText").textContent = loadingMessages[messageIndex];
        }, 1700);
    } else {
        btnText.classList.remove("hidden");
        btnLoader.classList.add("hidden");
        clearInterval(loadingTimer);
        loadingTimer = null;
    }
}

function showError(message) {
    const errorBox = document.getElementById("errorBox");

    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
}

function hideError() {
    const errorBox = document.getElementById("errorBox");

    errorBox.classList.add("hidden");
    errorBox.textContent = "";
}

function showResult(answer, threadId, flightResults, hotelResults) {
    latestAnswerMarkdown = answer;

    const resultSection = document.getElementById("resultSection");
    const resultBox = document.getElementById("resultBox");
    const threadInfo = document.getElementById("threadInfo");

    if (typeof marked !== "undefined") {
        resultBox.innerHTML = marked.parse(answer, { breaks: true });
    } else {
        resultBox.innerText = answer;
    }

    threadInfo.textContent = "Plan generated just now";
    threadInfo.title = `Conversation reference: ${threadId}`;
    renderOverview(flightResults, hotelResults);

    resultSection.classList.remove("hidden");

    resultSection.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}

function renderOverview(flightResults, hotelResults) {
    const overview = document.getElementById("planOverview");
    const items = [
        ["Flights", flightResults, "✈"],
        ["Stays", hotelResults, "⌂"]
    ];
    overview.innerHTML = items.map(([label, value, icon]) => {
        const text = String(value || "").trim();
        const summary = text ? text.replace(/[#*_`]/g, "").replace(/\s+/g, " ").slice(0, 150) : "Included in your plan";
        return `<div class="overview-item"><span class="overview-icon" aria-hidden="true">${icon}</span><div><strong>${label}</strong><p>${escapeHtml(summary)}${summary.length >= 150 ? "…" : ""}</p></div></div>`;
    }).join("");
}

function escapeHtml(value) {
    return value.replace(/[&<>"']/g, character => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"}[character]));
}

async function sendMessage() {
    hideError();

    const input = document.getElementById("userInput");
    const message = input.value.trim();

    if (!message) {
        showError("Please enter your travel request first.");
        return;
    }

    setLoading(true);

    try {
        const response = await fetch("/api/travel", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                message: message,
                thread_id: currentThreadId
            })
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Something went wrong.");
        }

        currentThreadId = data.thread_id;
        localStorage.setItem("travel_thread_id", currentThreadId);

        showResult(data.answer, data.thread_id, data.flight_results, data.hotel_results);

    } catch (error) {
        showError(error.message || "We couldn't create your plan. Please try again.");
    } finally {
        setLoading(false);
    }
}

function copyResult() {
    const resultBox = document.getElementById("resultBox");
    const text = resultBox.innerText;

    if (!text) {
        return;
    }

    navigator.clipboard.writeText(text)
        .then(() => {
            const copyBtn = document.querySelector(".copy-btn");
            const oldText = copyBtn.innerHTML;

            copyBtn.innerHTML = "<span aria-hidden=\"true\">✓</span> Copied";
            copyBtn.classList.add("is-success");

            setTimeout(() => {
                copyBtn.innerHTML = oldText;
                copyBtn.classList.remove("is-success");
            }, 1400);
        })
        .catch(() => {
            showError("Could not copy result.");
        });
}

function downloadPDF() {
    const pdfContent = document.getElementById("pdfContent");

    if (!latestAnswerMarkdown || !pdfContent) {
        showError("No travel plan available to download.");
        return;
    }

    const downloadBtn = document.querySelector(".download-btn");
    const oldText = downloadBtn.innerHTML;

    downloadBtn.innerHTML = "Preparing PDF...";
    downloadBtn.disabled = true;

    const options = {
        margin: 0.5,
        filename: "ai-travel-plan.pdf",
        image: {
            type: "jpeg",
            quality: 0.98
        },
        html2canvas: {
            scale: 2,
            useCORS: true,
            backgroundColor: "#ffffff"
        },
        jsPDF: {
            unit: "in",
            format: "a4",
            orientation: "portrait"
        },
        pagebreak: {
            mode: ["avoid-all", "css", "legacy"]
        }
    };

    html2pdf()
        .set(options)
        .from(pdfContent)
        .save()
        .then(() => {
            downloadBtn.innerHTML = oldText;
            downloadBtn.disabled = false;
        })
        .catch(() => {
            downloadBtn.innerHTML = oldText;
            downloadBtn.disabled = false;
            showError("Could not download PDF.");
        });
}

document.addEventListener("keydown", function(event) {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        sendMessage();
    }
});