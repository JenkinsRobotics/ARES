const scenes = [
  ["focus.sh", "Focus lighting"],
  ["movie.sh", "Movie lighting"],
  ["relax.sh", "Relax lighting"],
  ["sleep.sh", "Sleep lighting"],
  ["all-on.sh", "All lights on"],
  ["all-off.sh", "All lights off"],
  ["clean-up.sh", "Clean-up scene"],
  ["set-light.sh", "Set a single light"],
];
const ul = document.getElementById("scenes");
for (const [file, label] of scenes) {
  const li = document.createElement("li");
  li.innerHTML = "<strong>" + label + "</strong><br><code>scripts/" + file + "</code>";
  ul.appendChild(li);
}
