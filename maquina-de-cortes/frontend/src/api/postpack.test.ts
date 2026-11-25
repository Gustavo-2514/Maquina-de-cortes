import { describe, expect, it } from "vitest";
import {
  coverUrl,
  hasPostTexts,
  parsePost,
  parseTags,
  platformText,
} from "./clips";
import type { Clip, PostPack } from "./types";

const post: PostPack = {
  tiktok: { caption: "Olha isso", hashtags: ["fyp", "podcast"] },
  reels: { caption: "", hashtags: ["cortes"] },
  shorts: {
    title: "Título",
    description: "Sobre escolhas.",
    hashtags: ["podcast"],
  },
  cover_at: "2026-11-25T10:00:00Z",
};

describe("pacote para postar", () => {
  it("monta o texto de cada plataforma", () => {
    expect(platformText(post, "tiktok")).toBe("Olha isso\n\n#fyp #podcast");
    expect(platformText(post, "reels")).toBe("#cortes");
    expect(platformText(post, "shorts")).toBe(
      "Sobre escolhas.\n\n#podcast #Shorts",
    );
    expect(platformText({}, "tiktok")).toBe("");
  });

  it("lê hashtags digitadas de qualquer jeito", () => {
    expect(parseTags("#um dois,  #três ##quatro")).toEqual([
      "um",
      "dois",
      "três",
      "quatro",
    ]);
    expect(parseTags("  ")).toEqual([]);
  });

  it("tolera post_json vazio ou inválido e versiona a URL da capa", () => {
    const c = { id: 7, post_json: JSON.stringify(post) } as Clip;
    expect(hasPostTexts(parsePost(c))).toBe(true);
    expect(parsePost({ post_json: "x" } as Clip)).toEqual({});
    expect(hasPostTexts(parsePost({ post_json: "{}" } as Clip))).toBe(false);
    expect(coverUrl(c, true)).toBe(
      "/api/clips/7/cover?v=2026-11-25T10%3A00%3A00Z&titled=1",
    );
  });
});
