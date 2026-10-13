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
    throw new Error("登录服务尚未加载，请刷新页面后重试");
  }
  return firebase.auth();
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
    return saveFirebaseSession(result.user);
  },

  async registerWithEmail(email, password, displayName) {
    const name = displayName.trim();
    if (!name || name.length > 128) throw new Error("用户名需为 1–128 个字符");
    const result = await firebaseAuth().createUserWithEmailAndPassword(email, password);
    await result.user.updateProfile({ displayName: name });
    // Refresh so the first backend request sees the new name in the ID token.
    await result.user.getIdToken(true);
    return saveFirebaseSession(result.user);
  },

  async resetPassword(email) {
    await firebaseAuth().sendPasswordResetEmail(email);
  },

  errorMessage(error) {
    const messages = {
      "auth/invalid-credential": "邮箱或密码错误",
      "auth/user-not-found": "邮箱或密码错误",
      "auth/wrong-password": "邮箱或密码错误",
      "auth/email-already-in-use": "该邮箱已有账号，请登录或重置密码",
      "auth/weak-password": "密码强度不足，请使用更长的密码",
      "auth/invalid-email": "请输入有效邮箱",
      "auth/user-disabled": "该账号已停用",
      "auth/too-many-requests": "尝试次数过多，请稍后重试",
      "auth/network-request-failed": "登录服务连接失败，请检查网络",
      "auth/operation-not-allowed": "邮箱登录尚未启用，请联系管理员",
    };
    return messages[error.code] || error.message || "登录失败，请重试";
  },

  /**
   * Google 一键登录
   */
  async loginWithGoogle() {
    if (typeof firebase === "undefined" || !firebase.auth) {
      throw new Error("Firebase Auth SDK 尚未加载");
    }
    const provider = new firebase.auth.GoogleAuthProvider();
    provider.addScope("profile");
    provider.addScope("email");

    const result = await firebase.auth().signInWithPopup(provider);
    return saveFirebaseSession(result.user);
  },

  /**
   * 获取当前有效 ID Token (必要时自动刷新)
   */
  async getIdToken() {
    await firebaseAuthReady;
    if (typeof firebase !== "undefined" && firebase.auth().currentUser) {
      const token = await firebase.auth().currentUser.getIdToken(true);
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
        if (user) {
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
