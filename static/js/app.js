// Function triggered directly when typing in the input field
function updatePreviewText(text) {
  const textDisplay = document.getElementById("preview-text-display");
  const charCount = document.getElementById("char-count");
  const uppercaseText = text.toUpperCase();

  if (textDisplay) {
    textDisplay.textContent =
      uppercaseText.trim() === "" ? "YOUR TEXT HERE" : uppercaseText;

    // Auto-scale font size if text gets long
    if (uppercaseText.length > 18) {
      textDisplay.style.fontSize = "1.05rem";
    } else if (uppercaseText.length > 12) {
      textDisplay.style.fontSize = "1.25rem";
    } else {
      textDisplay.style.fontSize = "1.45rem";
    }
  }

  if (charCount) {
    charCount.textContent = `${text.length} / 24 characters`;
    charCount.style.color = text.length >= 24 ? "#e11d48" : "#6c757d";
  }
}

// Event listener fallback when page loads
document.addEventListener("DOMContentLoaded", () => {
  const textInput = document.getElementById("custom-text-input");
  if (textInput) {
    textInput.addEventListener("input", (e) => {
      updatePreviewText(e.target.value);
    });
  }
});

// Toggle finish options between Black/White and White/Black
function setFinish(finishClass) {
  const mockup = document.getElementById("mdf-sign-mockup");
  if (mockup) {
    mockup.className = "mdf-mockup " + finishClass;
  }

  // Update active button styling
  document
    .querySelectorAll(".finish-btn")
    .forEach((btn) => btn.classList.remove("active"));
  if (window.event && window.event.currentTarget) {
    window.event.currentTarget.classList.add("active");
  }
}