import { app } from "../../scripts/app.js";

app.registerExtension({
  name: "OpenAdFactory.App",
  commands: [
    {
      id: "OpenAdFactory.OpenApp",
      label: "Open Ad Factory",
      icon: "pi pi-video",
      function: () => window.open("/open_ad_factory/", "_blank"),
    },
  ],
  menuCommands: [{ path: ["Open Ad Factory"], commands: ["OpenAdFactory.OpenApp"] }],
});
