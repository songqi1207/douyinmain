import { createContext, useContext, useEffect, useMemo, useState } from "react";

export type ColorTheme = "mint" | "violet" | "sunset" | "ocean";
export type AppLanguage = "zh-CN" | "en";

type PreferencesContextValue = {
  theme: ColorTheme;
  language: AppLanguage;
  setTheme: (theme: ColorTheme) => void;
  setLanguage: (language: AppLanguage) => void;
  tr: (zh: string, en: string) => string;
  locale: string;
};

const DEFAULT_PREFERENCES: PreferencesContextValue = {
  theme: "mint",
  language: "zh-CN",
  setTheme: () => undefined,
  setLanguage: () => undefined,
  tr: (zh) => zh,
  locale: "zh-CN",
};

const PreferencesContext = createContext<PreferencesContextValue>(DEFAULT_PREFERENCES);

function readTheme(): ColorTheme {
  const saved = localStorage.getItem("videolab:color-theme");
  return saved === "violet" || saved === "sunset" || saved === "ocean" ? saved : "mint";
}

function readLanguage(): AppLanguage {
  return localStorage.getItem("videolab:language") === "en" ? "en" : "zh-CN";
}

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ColorTheme>(readTheme);
  const [language, setLanguageState] = useState<AppLanguage>(readLanguage);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("videolab:color-theme", theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.lang = language;
    localStorage.setItem("videolab:language", language);
  }, [language]);

  const value = useMemo<PreferencesContextValue>(() => ({
    theme,
    language,
    setTheme: setThemeState,
    setLanguage: setLanguageState,
    tr: (zh, en) => language === "en" ? en : zh,
    locale: language === "en" ? "en-US" : "zh-CN",
  }), [theme, language]);

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences() {
  return useContext(PreferencesContext);
}

export const COLOR_THEMES: Array<{ id: ColorTheme; zh: string; en: string }> = [
  { id: "mint", zh: "薄荷青", en: "Mint" },
  { id: "violet", zh: "云雾紫", en: "Violet" },
  { id: "sunset", zh: "日落橙", en: "Sunset" },
  { id: "ocean", zh: "海洋蓝", en: "Ocean" },
];
