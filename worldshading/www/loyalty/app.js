/* ==================== GLOBAL VARIABLES ==================== */
let verifiedMobile = null;
window._otpMobileFull = null;
const SECRET = "859687458WSLP789658745";

/* ==================== UTILITY FUNCTIONS ==================== */

/**
 * Format Bahrain mobile numbers to international format
 * @param {string} num - Phone number to normalize
 * @returns {string|null} - Normalized phone number or null if invalid
 */
function normalizeBahrainNumber(num) {
    num = num.replace(/\D/g, "");

    if (num.startsWith("973") && num.length === 11) return "+" + num;
    if (num.length === 8) return "+973" + num;
    if (num.startsWith("+973") && num.length === 12) return num;

    return null;
}

/* ==================== OTP FUNCTIONS ==================== */

/**
 * Show OTP verification popup
 */
function showOtpPopup() {
    document.getElementById("otpField").value = "";
    document.getElementById("otpSentText").textContent =
        "We've sent a verification code to " + window._otpMobileFull;

    document.getElementById("otpPopup").style.display = "flex";

    startOtpTimer();
}

/**
 * Close OTP popup
 */
function closeOtpPopup() {
    document.getElementById("otpPopup").style.display = "none";
    if (otpTimer) clearInterval(otpTimer);
}

/**
 * Start 30-second countdown timer for OTP resend
 */
let otpTimer = null;
function startOtpTimer() {
    let timeLeft = 30;
    const resendBtn = document.getElementById("resendBtn");
    resendBtn.disabled = true;
    resendBtn.style.opacity = "0.5";
    resendBtn.style.cursor = "not-allowed";

    resendBtn.textContent = `Resend OTP (${timeLeft}s)`;

    otpTimer = setInterval(() => {
        timeLeft--;
        resendBtn.textContent = `Resend OTP (${timeLeft}s)`;

        if (timeLeft <= 0) {
            clearInterval(otpTimer);
            resendBtn.disabled = false;
            resendBtn.style.opacity = "1";
            resendBtn.style.cursor = "pointer";
            resendBtn.textContent = "Resend OTP";
        }
    }, 1000);
}

/* ==================== MAIN LOYALTY CHECK FLOW ==================== */

/**
 * STEP 1: Check customer and send OTP
 */
document.getElementById("checkPointsBtn").addEventListener("click", async function () {
    const input = document.getElementById("customerInput").value.trim();
    const loading = document.getElementById("loading");
    const resultBox = document.getElementById("resultBox");

    if (!input) {
        alert("Please enter mobile number or customer ID");
        return;
    }

    loading.style.display = "block";
    resultBox.style.display = "none";

    try {
        // Step 1: Identify customer
        const response = await fetch(
            `/api/method/worldshading.api.loyalty.get_loyalty?customer_input=${input}&key=${SECRET}`
        );

        const data = await response.json();
        loading.style.display = "none";

        if (!data.message || data.message.status === "error") {
            alert("Customer not found. Please check your mobile number or customer ID.");
            return;
        }

        verifiedMobile = data.message.mobile;

        // Step 2: Normalize mobile for OTP
        window._otpMobileFull = normalizeBahrainNumber(verifiedMobile);
        if (!window._otpMobileFull) {
            alert("Invalid Bahrain mobile number format.");
            return;
        }

        // Step 3: Send OTP
        const otpRes = await fetch(
            `/api/method/worldshading.api.otp.send_otp?mobile=${window._otpMobileFull}`
        );
        const otpData = await otpRes.json();

        if (otpData.message.status !== "success") {
            alert("Failed to send OTP. Please try again.");
            return;
        }

        // Show OTP popup
        showOtpPopup();

    } catch (err) {
        loading.style.display = "none";
        alert("Server error. Please try again later.");
        console.error("Error:", err);
    }
});

/* ==================== OTP VERIFICATION ==================== */

/**
 * STEP 2: Verify OTP entered by user
 */
document.getElementById("verifyBtn").addEventListener("click", async () => {
    const otp = document.getElementById("otpField").value.trim();

    if (!otp) {
        alert("Please enter the OTP code");
        return;
    }

    if (otp.length !== 6) {
        alert("OTP must be 6 digits");
        return;
    }

    try {
        const verifyRes = await fetch(
            `/api/method/worldshading.api.otp.verify_otp?mobile=${window._otpMobileFull}&otp=${otp}`
        );

        const verifyData = await verifyRes.json();

        if (verifyData.message.status === "success") {
            closeOtpPopup();
            
            // Load loyalty data now that OTP is verified
            loadLoyaltyData(verifiedMobile);
        } else {
            alert("Incorrect OTP. Please try again.");
        }
    } catch (err) {
        alert("Verification error. Please try again.");
        console.error("Error:", err);
    }
});

/**
 * Resend OTP to user's mobile
 */
document.getElementById("resendBtn").addEventListener("click", async () => {
    try {
        const resend = await fetch(
            `/api/method/worldshading.api.otp.send_otp?mobile=${window._otpMobileFull}`
        );

        const resendData = await resend.json();

        if (resendData.message.status === "success") {
            startOtpTimer();
            alert("OTP resent successfully!");
        } else {
            alert("Failed to resend OTP. Please try again.");
        }
    } catch (err) {
        alert("Failed to resend OTP. Please try again.");
        console.error("Error:", err);
    }
});

/* ==================== LOAD LOYALTY DATA ==================== */

/**
 * STEP 3: Load and display loyalty data after OTP verification
 * @param {string} mobile - Verified mobile number
 */
async function loadLoyaltyData(mobile) {
    const loading = document.getElementById("loading");
    const resultBox = document.getElementById("resultBox");

    loading.style.display = "block";

    try {
        const response = await fetch(
            `/api/method/worldshading.api.loyalty.get_loyalty?customer_input=${mobile}&key=${SECRET}`
        );

        const data = await response.json();
        loading.style.display = "none";

        if (!data.message || data.message.status === "error") {
            resultBox.style.display = "block";
            resultBox.querySelector(".result-header").style.display = "none";
            resultBox.querySelector(".result-body").innerHTML = `
                <div class="not-found">
                    <div class="not-found-icon">🔍</div>
                    <div class="not-found-title">No Record Found</div>
                    <div class="not-found-text">${data.message?.message || "Please check your information"}</div>
                </div>
            `;
            return;
        }

        let d = data.message;

        // Show result
        resultBox.style.display = "block";
        resultBox.querySelector(".result-header").style.display = "block";

        // Update header information
        document.getElementById("customerName").textContent = d.customer_name;
        document.getElementById("customerId").textContent = d.customer_id;
        document.getElementById("pointsValue").textContent = d.points;

        // Rebuild result body structure
        resultBox.querySelector(".result-body").innerHTML = `
            <div class="info-row">
                <span class="info-label">📱 Mobile</span>
                <span class="info-value" id="customerMobile"></span>
            </div>
            <div class="info-row">
                <span class="info-label">🎯 Program</span>
                <span class="info-value" id="loyaltyProgram"></span>
            </div>
            <div class="info-row">
                <span class="info-label">⚡ Tier</span>
                <span class="info-value" id="tierBadge"></span>
            </div>
            <div class="info-row">
                <span class="info-label">📊 Collection Factor</span>
                <span class="info-value" id="collectionFactor"></span>
            </div>
            <div class="info-row">
                <span class="info-label">❌ Expired Points</span>
                <span class="info-value" id="expiredPoints"></span>
            </div>
            <div id="expiryWarning" class="expiry-warning" style="display: none;">
                <div class="expiry-warning-text">
                    ⚠️ <strong id="expiringPoints"></strong> points will expire on <strong id="expiryDate"></strong>
                </div>
            </div>
        `;

        // Populate data
        document.getElementById("customerMobile").textContent = d.mobile || "N/A";
        document.getElementById("loyaltyProgram").textContent = d.loyalty_program;
        document.getElementById("tierBadge").innerHTML = `<span class="tier-badge">${d.tier}</span>`;
        document.getElementById("collectionFactor").textContent = d.collection_factor;
        document.getElementById("expiredPoints").textContent = d.expired_points;

        // Show expiry warning if applicable
        if (d.upcoming_expiry_date && d.upcoming_expiry_points > 0) {
            document.getElementById("expiryWarning").style.display = "block";
            document.getElementById("expiringPoints").textContent = d.upcoming_expiry_points;
            document.getElementById("expiryDate").textContent = d.upcoming_expiry_date;
        }

    } catch (err) {
        loading.style.display = "none";
        alert("Server error. Please try again later.");
        console.error("Error:", err);
    }
}

/* ==================== NAVIGATION FUNCTIONS ==================== */

/**
 * Set active state for navigation items
 * @param {HTMLElement} clickedItem - The navigation item that was clicked
 */
function setActiveNav(clickedItem) {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });
    clickedItem.classList.add('active');
}

/**
 * Navigate to home section
 */
function showHome() {
    setActiveNav(event.currentTarget);
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

/**
 * Navigate to offers section (placeholder)
 */
function showOffers() {
    setActiveNav(event.currentTarget);
    alert("🎁 Offers section coming soon! Stay tuned for exclusive deals and promotions.");
}

/**
 * Navigate to history section (placeholder)
 */
function showHistory() {
    setActiveNav(event.currentTarget);
    alert("📊 Transaction history coming soon! You'll be able to view all your points activity here.");
}

/**
 * Navigate to profile section (placeholder)
 */
function showProfile() {
    setActiveNav(event.currentTarget);
    alert("👤 Profile section coming soon! Manage your account settings and preferences.");
}