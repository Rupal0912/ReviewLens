export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"] },
      colors: {
        ink: "#14202B", paper: "#F5F7F9", line: "#D8DEE4", muted: "#5B6875",
        pos: "#2E7D5B", neg: "#B23A2E", neu: "#8793A0", accent: "#2B4C7E",
      },
    },
  },
  plugins: [],
};
