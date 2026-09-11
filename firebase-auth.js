// ============================================================
// AURA - Firebase Auth Handler
// ============================================================
import { auth, db, googleProvider, signInWithPopup, signOut, onAuthStateChanged, collection, addDoc, getDocs } from "./firebase-config.js";

// ── Google Sign-In ──────────────────────────────────────────
export async function signInWithGoogle() {
  try {
    const result = await signInWithPopup(auth, googleProvider);
    const user = result.user;
    console.log("[AURA Auth] Signed in:", user.displayName, user.email);
    showUserInfo(user);
    return user;
  } catch (err) {
    console.error("[AURA Auth] Sign-in error:", err.message);
    alert("Login failed: " + err.message);
  }
}

// ── Sign Out ────────────────────────────────────────────────
export async function signOutUser() {
  try {
    await signOut(auth);
    console.log("[AURA Auth] Signed out.");
    hideUserInfo();
  } catch (err) {
    console.error("[AURA Auth] Sign-out error:", err.message);
  }
}

// ── Auth State Listener ─────────────────────────────────────
onAuthStateChanged(auth, (user) => {
  if (user) {
    console.log("[AURA Auth] User active:", user.email);
    showUserInfo(user);
  } else {
    console.log("[AURA Auth] No user signed in.");
    hideUserInfo();
  }
});

// ── UI Helpers ──────────────────────────────────────────────
function showUserInfo(user) {
  const el = document.getElementById("firebase-user-info");
  const btn = document.getElementById("firebase-login-btn");
  const out = document.getElementById("firebase-logout-btn");
  if (el)  el.textContent = "🔐 " + (user.displayName || user.email);
  if (btn) btn.style.display = "none";
  if (out) out.style.display = "inline-block";
}

function hideUserInfo() {
  const el = document.getElementById("firebase-user-info");
  const btn = document.getElementById("firebase-login-btn");
  const out = document.getElementById("firebase-logout-btn");
  if (el)  el.textContent = "";
  if (btn) btn.style.display = "inline-block";
  if (out) out.style.display = "none";
}

// ── Firestore: Save student data ────────────────────────────
export async function saveStudentToFirestore(studentData) {
  try {
    const docRef = await addDoc(collection(db, "students"), {
      ...studentData,
      createdAt: new Date().toISOString()
    });
    console.log("[AURA DB] Student saved to Firestore, ID:", docRef.id);
    return docRef.id;
  } catch (err) {
    console.error("[AURA DB] Firestore write error:", err);
  }
}

// ── Firestore: Get all students ──────────────────────────────
export async function getStudentsFromFirestore() {
  try {
    const snapshot = await getDocs(collection(db, "students"));
    const students = [];
    snapshot.forEach(doc => students.push({ id: doc.id, ...doc.data() }));
    console.log("[AURA DB] Fetched", students.length, "students from Firestore.");
    return students;
  } catch (err) {
    console.error("[AURA DB] Firestore read error:", err);
    return [];
  }
}

// Expose globally for non-module HTML usage
window.signInWithGoogle  = signInWithGoogle;
window.signOutUser       = signOutUser;
