const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { mergeCalibration, PreviewLoader } = require('../Source_code/static/js/calibration-projection.js');

const loaded = {
  camera: { camera_matrix: [[100, 0, 50], [0, 100, 100], [0, 0, 1]], dist_coeffs: [0.1, 0, 0, 0] },
  scale: {
    mode: 'homography', speed_window_seconds: 0.4,
    homography: {
      image_points: [[0, 0], [100, 0], [100, 200], [0, 200]], width_m: 10, length_m: 20,
      speed_distance_mode: 'euclidean',
      longitudinal_correction: { estimated_positions_m: [0, 20], corrected_positions_m: [0, 18] },
      world_points: [[0, 0], [10, 0], [10, 20], [0, 20]], ransac_reproj_threshold_px: 3,
    },
  },
};

test('preview/save payload retains camera, measured correction and speed settings', () => {
  const result = mergeCalibration(loaded, { scale: { mode: 'homography', homography: {
    image_points: loaded.scale.homography.image_points, width_m: 10, length_m: 20, interval_m: 5,
  } } });
  assert.deepEqual(result.camera, loaded.camera);
  assert.deepEqual(result.scale.homography.longitudinal_correction, loaded.scale.homography.longitudinal_correction);
  assert.equal(result.scale.speed_window_seconds, 0.4);
  assert.equal(result.scale.homography.speed_distance_mode, 'euclidean');
});

test('changing geometry invalidates old correction without losing camera calibration', () => {
  const result = mergeCalibration(loaded, { scale: { mode: 'homography', homography: { length_m: 25 } } });
  assert.deepEqual(result.camera, loaded.camera);
  for (const key of ['longitudinal_correction', 'world_points', 'ransac_reproj_threshold_px']) {
    assert.equal(result.scale.homography[key], undefined);
  }
  assert.ok(loaded.scale.homography.longitudinal_correction);
});

test('older preview cannot replace a newer render and identical requests reuse the image', async () => {
  const originalFetch = global.fetch;
  const originalImage = global.Image;
  const pending = [];
  global.Image = class { async decode() {} };
  global.fetch = () => new Promise(resolve => pending.push(resolve));
  try {
    const loader = new PreviewLoader();
    const old = loader.load('/preview', { frame: 1 }, loader.invalidate());
    const recent = loader.load('/preview', { frame: 2 }, loader.invalidate());
    pending[1]({ ok: true, json: async () => ({ image: 'new', frame: 2 }) });
    assert.equal((await recent).frame, 2);
    pending[0]({ ok: true, json: async () => ({ image: 'old', frame: 1 }) });
    assert.equal(await old, null);
    const cached = await loader.load('/preview', { frame: 2 }, loader.invalidate());
    assert.equal(cached.frame, 2);
    assert.equal(pending.length, 2);
  } finally {
    global.fetch = originalFetch;
    global.Image = originalImage;
  }
});

test('calibration editor inline JavaScript parses', () => {
  const html = fs.readFileSync(require('node:path').join(__dirname, '../templates/calibration.html'), 'utf8');
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  assert.ok(scripts.length);
  for (const script of scripts) new vm.Script(script[1]);
});
