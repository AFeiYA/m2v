const assert = require('node:assert/strict');
const {test} = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../firebase-config.js'), 'utf8');

function setup(initialUser = null) {
  const values = new Map([['m2v_token', 'stale-token'], ['m2v_refresh', 'other-account']]);
  const calls = [];
  const user = {uid: 'firebase-email-user', email: 'test@example.com', displayName: '', emailVerified: false,
    getIdToken: async force => {calls.push(['token', !!force]); return 'firebase-id-token';},
    updateProfile: async data => {calls.push(['profile', data.displayName]); user.displayName = data.displayName;},
    reauthenticateWithCredential: async cred => {calls.push(['reauthenticate', cred]);},
    updatePassword: async pwd => {calls.push(['updatePassword', pwd]);},
    sendEmailVerification: async (settings) => {calls.push(['verification', settings]);},
    reload: async () => {calls.push(['reload']);},
  };
  const auth = {
    currentUser: initialUser,
    onAuthStateChanged(callback) {queueMicrotask(() => callback(auth.currentUser)); return () => {};},
    async createUserWithEmailAndPassword(email, password) {calls.push(['signup', email, password]); auth.currentUser = user; return {user};},
    async signInWithEmailAndPassword(email, password) {calls.push(['login', email, password]); auth.currentUser = user; return {user};},
    async sendPasswordResetEmail(email, settings) {calls.push(['reset', email, settings]);},
    async verifyPasswordResetCode(code) {calls.push(['verifyCode', code]); return 'test@example.com';},
    async confirmPasswordReset(code, password) {calls.push(['confirmReset', code, password]);},
    async applyActionCode(code) {calls.push(['applyCode', code]);},
    async signOut() {auth.currentUser = null;},
  };
  const authFn = () => auth;
  authFn.EmailAuthProvider = {
    credential: (email, pwd) => ({email, pwd, type: 'credential'}),
  };
  const context = {window: {location: {origin: 'https://mv.fovea.si'}}, firebase: {apps: [{}], auth: authFn},
    localStorage: {getItem: k => values.get(k) || null, setItem: (k,v) => values.set(k,v), removeItem: k => values.delete(k)},
  };
  vm.createContext(context); vm.runInContext(source, context);
  return {helper: context.window.m2vAuth, calls, values, auth, user};
}

test('email signup sends verification and does not create an app session before verification', async () => {
  const s = setup();
  const result = await s.helper.registerWithEmail('test@example.com', 'long-password', 'Artist');
  assert.equal(result.verificationRequired, true);
  assert.deepEqual(s.calls.map(c => c[0]), ['signup', 'profile', 'verification']);
  assert.ok(![...s.values.values()].some(v => String(v).includes('long-password')));
});

test('email login uses Firebase and clears credentials from the previous local account', async () => {
  const s = setup();
  const pending = await s.helper.loginWithEmail('test@example.com', 'long-password');
  assert.equal(pending.verificationRequired, true);
  s.auth.currentUser.emailVerified = true;
  await s.helper.checkEmailVerification();
  assert.equal(s.calls[0][0], 'login');
  assert.equal(s.values.get('m2v_token'), 'firebase-id-token');
  assert.equal(s.values.has('m2v_refresh'), false);
});

test('verification can be retried and forces a fresh verified token', async () => {
  const s = setup();
  await s.helper.registerWithEmail('test@example.com', 'long-password', 'Artist');
  await s.helper.resendVerification();
  assert.equal((await s.helper.checkEmailVerification()).verificationRequired, true);
  s.auth.currentUser.emailVerified = true;
  const result = await s.helper.checkEmailVerification();
  assert.equal(result.idToken, 'firebase-id-token');
  assert.ok(s.calls.some(c => c[0] === 'token' && c[1] === true));
});

test('missing Firebase user never returns the stale cached token', async () => {
  const s = setup();
  assert.equal(await s.helper.getIdToken(), null);
});

test('password reset and authentication errors have explicit handling', async () => {
  const s = setup();
  await s.helper.resetPassword('test@example.com');
  assert.equal(s.auth.languageCode, 'en');
  assert.equal(s.calls[0][0], 'reset');
  assert.equal(s.calls[0][1], 'test@example.com');
  assert.equal(s.calls[0][2]?.url, 'https://mv.fovea.si/app');
  assert.equal(s.calls[0][2]?.handleCodeInApp, false);
  assert.equal(s.helper.errorMessage({code: 'auth/invalid-credential'}), 'Incorrect email or password.');
  assert.equal(s.helper.errorMessage({code: 'auth/user-not-found'}), 'Incorrect email or password.');
  assert.equal(s.helper.errorMessage({code: 'auth/email-already-in-use'}), 'This email already has an account. Sign in or reset your password.');
  assert.equal(s.helper.errorMessage({code: 'auth/missing-email'}), 'Enter your email address.');
  assert.equal(s.helper.errorMessage({code: 'auth/expired-action-code'}), 'This link has expired. Please request a new one.');
});

test('action code handlers verify, confirm reset, and apply codes', async () => {
  const s = setup();
  const email = await s.helper.verifyPasswordResetCode('test-oob-code');
  assert.equal(email, 'test@example.com');
  await s.helper.confirmPasswordReset('test-oob-code', 'new-long-password');
  await s.helper.applyActionCode('verify-oob-code');
  assert.deepEqual(s.calls, [
    ['verifyCode', 'test-oob-code'],
    ['confirmReset', 'test-oob-code', 'new-long-password'],
    ['applyCode', 'verify-oob-code'],
  ]);
});

test('changePassword re-authenticates with current password and updates to new password', async () => {
  const s = setup();
  s.auth.currentUser = s.user;
  await s.helper.changePassword('old-password', 'new-secure-password');
  assert.equal(s.calls.some(c => c[0] === 'reauthenticate' && c[1]?.pwd === 'old-password'), true);
  assert.equal(s.calls.some(c => c[0] === 'updatePassword' && c[1] === 'new-secure-password'), true);

  await assert.rejects(s.helper.changePassword('', 'new-secure-password'), /Current password is required/);
  await assert.rejects(s.helper.changePassword('old-password', 'short12'), /at least 8 characters/);
  await assert.rejects(s.helper.changePassword('same-pwd', 'same-pwd'), /different from current/);

  s.user.reauthenticateWithCredential = async () => {
    const err = new Error('invalid');
    err.code = 'auth/wrong-password';
    throw err;
  };
  await assert.rejects(s.helper.changePassword('wrong-pwd', 'new-secure-password'), /Current password is incorrect/);
});

test('invalid display names do not create a partially configured account', async () => {
  const s = setup();
  await assert.rejects(s.helper.registerWithEmail('test@example.com', 'password', ''), /Display name/);
  assert.deepEqual(s.calls, []);
});
