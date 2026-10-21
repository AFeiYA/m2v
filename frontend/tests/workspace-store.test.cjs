const assert = require('node:assert/strict');
const { test } = require('node:test');
const { WorkspaceStore } = require('../workspace-store.js');

test('WorkspaceStore manages user, song, and section state with reactive subscribers', () => {
  const store = new WorkspaceStore();
  const events = [];
  const unsubscribe = store.subscribe((state, action, payload) => {
    events.push({ action, payload });
  });

  // 1. User login
  store.setUser({ id: 'user-1', displayName: 'Alice' }, 'firebase');
  assert.equal(store.getState().account.isAuthenticated, true);
  assert.equal(store.getState().account.user.displayName, 'Alice');
  assert.equal(events.length, 1);
  assert.equal(events[0].action, 'USER_CHANGED');

  // 2. Set active song
  store.setActiveSong({ id: 'song-1', title: 'Bohemian Rhapsody', artist: 'Queen' });
  assert.equal(store.getState().song.activeSong.title, 'Bohemian Rhapsody');
  assert.equal(store.getState().song.activeVersionId, 'song-1');
  assert.equal(store.getState().song.isDirty, false);

  // 3. Mark dirty & set version
  store.setDirty(true);
  assert.equal(store.getState().song.isDirty, true);
  store.setLyricVersion('ver-2', 'etag-v2');
  assert.equal(store.getState().song.activeVersionId, 'ver-2');
  assert.equal(store.getState().song.savedVersion, 'etag-v2');

  // 4. Switch section
  store.setActiveSection('motion-studio-section');
  assert.equal(store.getState().navigation.activeStudio, 'motion');

  // 5. Logout clears everything
  store.clearUser();
  assert.equal(store.getState().account.isAuthenticated, false);
  assert.equal(store.getState().account.user, null);
  assert.equal(store.getState().song.activeSong, null);
  assert.equal(store.getState().song.isDirty, false);

  unsubscribe();
  store.setActiveSong({ id: 'song-2', title: 'Another One' });
  // No new events after unsubscribe
  assert.equal(events[events.length - 1].action, 'USER_LOGOUT');
});

test('separate editor draft states survive view changes and clear on logout',()=>{
 const store=new WorkspaceStore();store.setActiveSong({id:'song',title:'Song'});
 store.setEditorState('lyric',{songId:'song',dirty:true,saving:false});
 store.setActiveSection('motion-studio-section');
 assert.equal(store.getState().editors.lyric.dirty,true);
 store.setEditorState('motion',{songId:'song',dirty:true});
 store.setEditorState('lyric',{songId:'song',dirty:false});
 assert.equal(store.getState().song.isDirty,true);
 store.clearUser();
 assert.equal(store.getState().editors.motion.dirty,false);
 assert.equal(store.getState().editors.lyric.songId,null);
});
