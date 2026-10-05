'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../ui/app.js'), 'utf8');
const recording = source.slice(source.indexOf('async function toggleRecording()'), source.indexOf('async function uploadDocument'));
function fixture(getUserMedia) {
  const state = {recording: null, acquiring: false, preferences: {}}, activity = [];
  const context = {state, navigator: {mediaDevices: {getUserMedia}},
    MediaRecorder: function () { throw Error('A cancelled grant must not start recording'); },
    interrupt: async () => {}, setActivity: text => activity.push(text),
    $: () => ({}), document: {}, window: {}, console};
  vm.createContext(context);
  vm.runInContext(recording + '\nglobalThis.toggle = toggleRecording;', context);
  return {state, activity, toggle: context.toggle};
}
test('second microphone click cancels pending permission and releases the late stream', async () => {
  let grant, calls = 0, stopped = 0;
  const f = fixture(() => {calls++; return new Promise(resolve => {grant = resolve;});});
  const pending = f.toggle();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.state.acquiring, true);
  await f.toggle();
  assert.equal(f.state.acquiring, false);
  grant({getTracks: () => [{stop: () => stopped++}]});
  await pending;
  assert.equal(calls, 1);
  assert.equal(stopped, 1);
  assert.equal(f.state.recording, null);
});
test('denied microphone resets acquisition and allows another deliberate request', async () => {
  let calls = 0;
  const f = fixture(async () => {calls++; throw Error('Permission denied');});
  await assert.rejects(f.toggle(), /Permission denied/);
  assert.equal(f.state.acquiring, false);
  await assert.rejects(f.toggle(), /Permission denied/);
  assert.equal(calls, 2);
  assert.match(f.activity.at(-1), /not granted/);
});
