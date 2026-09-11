// ============================================================
// AURA - Firebase Configuration & Initialization
// ============================================================
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import { getFirestore, collection, addDoc, getDocs, doc, updateDoc, deleteDoc, query, where, orderBy } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";
import { getAnalytics } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-analytics.js";

const firebaseConfig = {
  apiKey: "AIzaSyBSJgFAw2tcQoQaJGOy10PpeZl3QojB-E8",
  authDomain: "aura-7a33d.firebaseapp.com",
  projectId: "aura-7a33d",
  storageBucket: "aura-7a33d.firebasestorage.app",
  messagingSenderId: "828357548043",
  appId: "1:828357548043:web:a5c1c0ba0129f2ada00f0e",
  measurementId: "G-PQ92214Y34"
};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);
const analytics = getAnalytics(app);
const googleProvider = new GoogleAuthProvider();

export { app, auth, db, analytics, googleProvider, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged, collection, addDoc, getDocs, doc, updateDoc, deleteDoc, query, where, orderBy };
