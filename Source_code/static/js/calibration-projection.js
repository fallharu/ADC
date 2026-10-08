/* Keep preview and saved calibration metadata identical. */
(function (root) {
  function mergeCalibration(loaded, edited) {
    const previous = loaded || {};
    const scale = { ...(previous.scale || {}), ...(edited.scale || {}) };
    if (scale.mode === 'homography') {
      const oldGeometry = previous.scale?.homography || {};
      const newGeometry = edited.scale?.homography || {};
      const unchanged = ['image_points', 'width_m', 'length_m'].every(
        key => JSON.stringify(oldGeometry[key]) === JSON.stringify(newGeometry[key])
      );
      const homography = { ...oldGeometry, ...newGeometry };
      if (!unchanged) {
        // These values are calibrated against a particular set of four points.
        for (const key of ['longitudinal_correction', 'world_points', 'ransac_reproj_threshold_px']) {
          delete homography[key];
        }
      }
      scale.homography = homography;
    }
    return { ...previous, ...edited, scale };
  }

  // One cached render, with cancellation and stale-response protection.
  class PreviewLoader {
    constructor() {
      this.sequence = 0;
      this.cached = null;
      this.controller = null;
    }
    invalidate() {
      this.sequence += 1;
      this.controller?.abort();
      return this.sequence;
    }
    async load(url, body, sequence) {
      const key = JSON.stringify([url, body]);
      if (this.cached?.key === key) return this.cached.value;
      this.controller = new AbortController();
      const response = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body), signal: this.controller.signal,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '俯瞰画像を生成できません。');
      const image = new Image();
      image.src = data.image;
      await image.decode();
      if (sequence !== this.sequence) return null;
      const value = { ...data, image };
      this.cached = { key, value };
      return value;
    }
  }
  root.CalibrationProjection = { mergeCalibration, PreviewLoader };
  if (typeof module !== 'undefined') module.exports = root.CalibrationProjection;
})(typeof window === 'undefined' ? globalThis : window);
