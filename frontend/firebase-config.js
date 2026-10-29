// Firebase Web App Configuration & Auth Client
// Project: dc-test-731fa
// App: M2V Web (1:961193736563:web:7b77569a14b8b9b4322d06)

const firebaseConfig = {
  projectId: "dc-test-731fa",
  appId: "1:961193736563:web:7b77569a14b8b9b4322d06",
  databaseURL: "https://dc-test-731fa.firebaseio.com",
  storageBucket: "dc-test-731fa.firebasestorage.app",
  apiKey: "AIzaSyCtyu4zxTfgpCnxmqv2u5APw61XlNW1AmI",
  authDomain: "auth.fovea.si",
  messagingSenderId: "961193736563",
  measurementId: "G-TSXRFYJQ6L"
};

// Initialize Firebase if not already initialized
if (typeof firebase !== "undefined" && !firebase.apps.length) {
  firebase.initializeApp(firebaseConfig);
}

function firebaseAuth() {
  if (typeof firebase === "undefined" || !firebase.auth) {
    throw new Error("Sign-in is unavailable. Please refresh and try again.");
  }
  const auth = firebase.auth();
  auth.languageCode = window.currentLocale === "zh" ? "zh-CN" : "en";
  return auth;
}

async function saveFirebaseSession(user) {
  const idToken = await user.getIdToken();
  localStorage.setItem("m2v_token", idToken);
  localStorage.setItem("m2v_auth_provider", "firebase");
  localStorage.removeItem("m2v_refresh");
  localStorage.setItem("m2v_user", JSON.stringify({
    uid: user.uid, email: user.email,
    displayName: user.displayName, photoURL: user.photoURL,
  }));
  return { user, idToken };
}

// Wait for Firebase to restore its persisted session before using cached tokens.
const firebaseAuthReady = typeof firebase !== "undefined" && firebase.auth
  ? new Promise(resolve => {
    const unsubscribe = firebase.auth().onAuthStateChanged(user => {
      unsubscribe();
      resolve(user);
    });
  }) : Promise.resolve(null);

// M2V Authentication Helper
window.m2vAuth = {
  config: firebaseConfig,
  ready: firebaseAuthReady,

  async loginWithEmail(email, password) {
    const result = await firebaseAuth().signInWithEmailAndPassword(email, password);
    if (result.user.emailVerified === false) return {user: result.user, verificationRequired: true};
    return saveFirebaseSession(result.user);
  },

  async registerWithEmail(email, password, displayName) {
    const name = displayName.trim();
    if (!name || name.length > 128) throw new Error("Display name must contain 1–128 characters.");
    const result = await firebaseAuth().createUserWithEmailAndPassword(email, password);
    await result.user.updateProfile({ displayName: name });
    if (result.user.emailVerified === false) {
      let verificationError = null;
      try { await result.user.sendEmailVerification(); } catch (error) { verificationError = error; }
      return {user: result.user, verificationRequired: true, verificationError};
    }
    // Refresh so the first backend request sees the new name in the ID token.
    await result.user.getIdToken(true);
    return saveFirebaseSession(result.user);
  },

  async resetPassword(email) {
    await firebaseAuth().sendPasswordResetEmail(email);
  },

  async resendVerification() {
    const user = firebaseAuth().currentUser;
    if (!user) throw new Error("Sign in to resend the verification email.");
    await user.sendEmailVerification();
  },

  async checkEmailVerification() {
    const user = firebaseAuth().currentUser;
    if (!user) throw new Error("Sign in to check your email verification.");
    await user.reload();
    if (!user.emailVerified) return {user, verificationRequired: true};
    await user.getIdToken(true);
    return saveFirebaseSession(user);
  },

  errorMessage(error) {
    const messages = {
      "auth/invalid-credential": "Incorrect email or password.",
      "auth/user-not-found": "Incorrect email or password.",
      "auth/wrong-password": "Incorrect email or password.",
      "auth/email-already-in-use": "This email already has an account. Sign in or reset your password.",
      "auth/weak-password": "Password is too weak. Use a longer password.",
      "auth/invalid-email": "Enter a valid email address.",
      "auth/user-disabled": "This account has been disabled.",
      "auth/too-many-requests": "Too many attempts. Please try again later.",
      "auth/network-request-failed": "Cannot connect to sign-in. Check your connection.",
      "auth/operation-not-allowed": "Email sign-in is unavailable. Please contact support.",
    };
    return messages[error.code] || error.message || "Sign-in failed. Please try again.";
  },

  /**
   * Google 一键登录
   */
  async loginWithGoogle() {
    if (typeof firebase === "undefined" || !firebase.auth) {
      throw new Error("The Firebase Auth SDK has not loaded.");
    }
    const provider = new firebase.auth.GoogleAuthProvider();
    provider.addScope("profile");
    provider.addScope("email");

    const result = await firebaseAuth().signInWithPopup(provider);
    return saveFirebaseSession(result.user);
  },

  /**
   * 获取当前有效 ID Token (必要时自动刷新)
   */
  async getIdToken(forceRefresh = true) {
    await firebaseAuthReady;
    if (typeof firebase !== "undefined" && firebase.auth().currentUser) {
      if (firebase.auth().currentUser.emailVerified === false) return null;
      const token = await firebase.auth().currentUser.getIdToken(forceRefresh);
      localStorage.setItem("m2v_token", token);
      return token;
    }
    return null;
  },

  /**
   * 退出登录
   */
  async logout() {
    if (typeof firebase !== "undefined" && firebase.auth) {
      await firebase.auth().signOut();
    }
    localStorage.removeItem("m2v_token");
    localStorage.removeItem("m2v_user");
  },

  /**
   * 监听登录状态变化
   */
  onAuthStateChanged(callback) {
    if (typeof firebase !== "undefined" && firebase.auth) {
      return firebase.auth().onAuthStateChanged(async (user) => {
        if (user && user.emailVerified !== false) {
          const token = await user.getIdToken();
          localStorage.setItem("m2v_token", token);
          localStorage.setItem("m2v_user", JSON.stringify({
            uid: user.uid,
            email: user.email,
            displayName: user.displayName,
            photoURL: user.photoURL,
          }));
        } else {
          localStorage.removeItem("m2v_token");
          localStorage.removeItem("m2v_user");
        }
        callback(user);
      });
    }
  }
};
