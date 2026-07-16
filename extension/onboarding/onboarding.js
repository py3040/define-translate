const PRIVACY_POLICY_URL = "https://pybuilds.com/define-translate/privacy";

const agreeBtn    = document.getElementById("agree-btn");
const declineBtn  = document.getElementById("decline-btn");
const backBtn     = document.getElementById("back-btn");
const consentView = document.getElementById("consent-view");
const declineView = document.getElementById("decline-view");
const privacyLink = document.getElementById("privacy-link");

privacyLink.href = PRIVACY_POLICY_URL;

agreeBtn.addEventListener("click", async () => {
  agreeBtn.disabled = true;
  agreeBtn.textContent = "Setting up…";
  await chrome.storage.local.set({
    userConsent: true,
    userConsentDate: new Date().toISOString(),
  });
  window.close();
});

declineBtn.addEventListener("click", () => {
  consentView.hidden = true;
  declineView.hidden = false;
});

backBtn.addEventListener("click", () => {
  declineView.hidden = true;
  consentView.hidden = false;
});
