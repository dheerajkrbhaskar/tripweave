let currentThreadId = localStorage.getItem("travel_thread_id") || null;
let latestAnswerMarkdown = "";
let loadingTimer = null;
let workflowState = "IDLE";
const loadingMessages = [
    "Understanding your trip...",
    "Searching for flights...",
    "Finding hotels...",
    "Building your itinerary...",
    "Preparing your draft..."
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

function setWorkflowState(state) {
    workflowState = state;
    const sendBtn = document.getElementById("sendBtn");
    const approvalPanel = document.getElementById("approvalPanel");
    const approveBtn = document.getElementById("approveBtn");
    const changesBtn = document.getElementById("changesBtn");
    const downloadBtn = document.getElementById("downloadBtn");

    sendBtn.disabled = state === "PLANNING" || state === "RESUMING";
    if (approvalPanel) {
        approvalPanel.classList.toggle("hidden", state !== "WAITING_FOR_APPROVAL");
    }
    if (approveBtn && changesBtn) {
        const resuming = state === "RESUMING";
        approveBtn.disabled = resuming;
        changesBtn.disabled = resuming;
        approveBtn.setAttribute("aria-busy", String(resuming));
        changesBtn.setAttribute("aria-busy", String(resuming));
    }
    if (downloadBtn) {
        downloadBtn.disabled = state === "WAITING_FOR_APPROVAL" || state === "RESUMING";
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

function showResult(data) {
    const answer = data.answer || data.itinerary || "";
    latestAnswerMarkdown = answer;

    const resultSection = document.getElementById("resultSection");
    const resultBox = document.getElementById("resultBox");
    const threadInfo = document.getElementById("threadInfo");
    const resultEyebrow = document.querySelector(".result-header .eyebrow");
    const resultTitle = document.querySelector(".result-header h2");
    const draftNotice = document.getElementById("draftNotice");
    const approvalRequest = document.getElementById("approvalRequest");
    const hasItinerary = Array.isArray(data.selected_agents)
        && data.selected_agents.includes("itinerary_agent");

    if (typeof marked !== "undefined") {
        resultBox.innerHTML = marked.parse(answer, { breaks: true });
    } else {
        resultBox.innerText = answer;
    }

    const draft = data.requires_approval === true;
    resultEyebrow.textContent = draft
        ? "DRAFT ITINERARY"
        : (hasItinerary ? "YOUR PERSONAL ITINERARY" : "TRAVEL INFORMATION");
    resultTitle.textContent = draft
        ? "Review your thoughtfully arranged trip."
        : (hasItinerary ? "Your trip, thoughtfully arranged." : "Here’s what we found.");
    threadInfo.textContent = draft ? "Waiting for your review" : "Plan generated just now";
    threadInfo.title = `Conversation reference: ${data.thread_id}`;
    draftNotice.classList.toggle("hidden", !draft);
    approvalRequest.textContent = data.approval_request || "Approve this draft or tell us what you would like changed.";
    renderReviewContext(data);
    resultSection.classList.remove("hidden");

    resultSection.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}

function renderReviewContext(data) {
    const context = document.getElementById("reviewContext");
    const summary = document.getElementById("constraintSummary");
    const warnings = document.getElementById("constraintWarnings");
    const constraints = data.trip_constraints || {};
    const entries = [
        ["Route", [constraints.origin, constraints.destination].filter(Boolean).join(" → ")],
        ["Duration", constraints.duration],
        ["Budget", constraints.budget],
        ["Preferences", Array.isArray(constraints.special_preferences)
            ? constraints.special_preferences.join(" · ")
            : constraints.special_preferences],
    ].filter(([, value]) => value);

    summary.innerHTML = entries.map(([label, value]) =>
        `<span><strong>${escapeHtml(label)}:</strong> ${escapeHtml(String(value))}</span>`
    ).join("");
    const warningItems = Array.isArray(data.constraint_warnings)
        ? data.constraint_warnings.filter(Boolean)
        : [];
    warnings.innerHTML = warningItems.length
        ? `<strong>Budget alert:</strong> ${warningItems.map(escapeHtml).join(" ")}`
        : "";
    context.classList.toggle("hidden", !entries.length && !warningItems.length);
}

function escapeHtml(value) {
    return value.replace(/[&<>"']/g, character => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"}[character]));
}

function validateResponse(data) {
    if (!data || typeof data !== "object") {
        throw new Error("The travel service returned an invalid response.");
    }
    if (typeof data.thread_id !== "string" || !data.thread_id) {
        throw new Error("The travel service did not return a valid conversation reference.");
    }
    if (typeof data.requires_approval !== "boolean") {
        throw new Error("The travel service returned an incomplete workflow response.");
    }
    return data;
}

function handleWorkflowResponse(data) {
    validateResponse(data);
    currentThreadId = data.thread_id;
    localStorage.setItem("travel_thread_id", currentThreadId);

    if (data.guardrail_allowed === false) {
        setWorkflowState("GUARDRAIL_BLOCKED");
        showResult({
            ...data,
            answer: data.guardrail_reason || "This request is outside travel planning."
        });
        document.getElementById("draftNotice").classList.add("hidden");
        document.querySelector(".result-header .eyebrow").textContent = "REQUEST NOT SUPPORTED";
        document.querySelector(".result-header h2").textContent = "Let’s keep your next plan travel-focused.";
        return;
    }

    showResult(data);
    if (data.requires_approval === true) {
        setWorkflowState("WAITING_FOR_APPROVAL");
    } else {
        setWorkflowState("COMPLETED");
    }
}

async function sendMessage() {
    hideError();

    const input = document.getElementById("userInput");
    const message = input.value.trim();

    if (!message) {
        showError("Please enter your travel request first.");
        return;
    }

    setWorkflowState("PLANNING");
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
        handleWorkflowResponse(data);

    } catch (error) {
        setWorkflowState("ERROR");
        showError(error.message || "We couldn't create your plan. Please try again.");
    } finally {
        setLoading(false);
    }
}

async function resumePlan(approved) {
    if (workflowState !== "WAITING_FOR_APPROVAL" || !currentThreadId) {
        return;
    }

    const feedbackInput = document.getElementById("feedbackInput");
    const feedback = feedbackInput.value.trim();
    if (!approved && feedback.length < 3) {
        feedbackInput.focus();
        showError("Please tell us what you would like changed before requesting revisions.");
        return;
    }

    hideError();
    setWorkflowState("RESUMING");
    setLoading(true);
    document.getElementById("loadingText").textContent = approved
        ? "Finalizing your travel plan..."
        : "Updating your travel plan...";

    try {
        const response = await fetch("/api/travel", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                thread_id: currentThreadId,
                approved: approved,
                feedback: feedback
            })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || "We couldn't update your travel plan.");
        }
        handleWorkflowResponse(data);
    } catch (error) {
        setWorkflowState("ERROR");
        showError(error.message || "We couldn't update your travel plan. Please try again.");
        setWorkflowState(currentThreadId ? "WAITING_FOR_APPROVAL" : "ERROR");
    } finally {
        setLoading(false);
    }
}

function approvePlan() {
    resumePlan(true);
}

function requestChanges() {
    resumePlan(false);
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

setWorkflowState("IDLE");