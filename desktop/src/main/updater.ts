/**
 * Auto-update wiring (stub for Phase 0).
 *
 * The real update feed + signing is configured in packaging (electron-builder.yml + a release
 * channel). Here we wire the entrypoints so the shape exists; it no-ops in dev and until a feed
 * is configured. Graduated in later phases alongside signed releases.
 */

export interface Updater {
  checkForUpdates(): Promise<void>;
}

export function createUpdater(options: { enabled: boolean; log: (m: string) => void }): Updater {
  return {
    async checkForUpdates() {
      if (!options.enabled) {
        options.log("auto-update disabled (dev / no feed configured)");
        return;
      }
      // Phase 0 stub: in production this uses electron-updater against the release feed.
      //   const { autoUpdater } = await import("electron-updater");
      //   autoUpdater.logger = ...; await autoUpdater.checkForUpdatesAndNotify();
      options.log("auto-update check requested (feed not yet configured)");
    },
  };
}
