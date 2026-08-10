"""Starter content for the welcome-email template feature.

``STARTER_SUBJECT`` / ``STARTER_HTML_BODY`` are the ultimate fallback used
by ``welcome_email.resolve_welcome_email_template`` when a flow has no
``WelcomeEmailTemplate`` of its own *and* no template anywhere in the
system is marked ``is_default_fallback`` — i.e. a fresh install where no
manager has edited a welcome email yet. They're also what the "Velkomstmail"
editor pre-fills for a brand-new flow so there's always a real, polished
starting point rather than a blank textarea.

This is the actual email a BCT manager sent to a real new hire (see the
PR/session that added this feature), genericised with two merge tags:

* ``Kære Silas,`` -> ``Kære {{ employee_first_name }},``
* ``Din buddy er: Rasmus`` -> ``{% if buddy_name %}Din buddy er: {{ buddy_name }}{% else %}...{% endif %}``

Everything else — the company/culture copy, the two-week timeline, the
follow-up meeting cadence, lunch/fitness/parking sections, and the
"Hvad skal du nu?" checklist — is the original content verbatim. It's
static company information, not per-hire data, so it doesn't need a merge
tag; managers can freely rewrite any of it in the editor.
"""
from __future__ import annotations

STARTER_SUBJECT = "Velkommen til Black Capital Technology, {{ employee_first_name }}!"

STARTER_HTML_BODY = """<!doctype html>
<html lang="da">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <meta name="x-apple-disable-message-reformatting" />
    <meta name="color-scheme" content="light" />
    <title>Velkommen til Black Capital Technology</title>
    <!--
      LOGO (CID) GUIDE:
      1) Attach the logo as an inline attachment
      2) Set Content-ID to: bctlogo
      3) This template references it as: src="cid:bctlogo"
      If you use a hosted image instead, replace with https://.../logo.png
    -->
  </head>

  <body style="margin:0;padding:0;background:#f5f7ff;">
    <!-- Preheader (hidden) -->
    <div
      style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;mso-hide:all;"
    >
      Velkommen til Black Capital Technology – her er din opstart, buddy-info og næste skridt.
    </div>

    <!-- Full width wrapper -->
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f5f7ff;">
      <tr>
        <td align="center" style="padding:32px 16px;">
          <!-- Container -->
          <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="width:600px;max-width:600px;">
            <!-- Header -->
            <tr>
              <td
                style="
                  background:#1a2a74;
                  padding:22px 24px;
                  border-radius:16px 16px 0 0;
                "
              >
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                  <tr>
                    <td align="left" style="vertical-align:middle;">
                      <img
                        src="https://blackcapitaltechnology.com/wp-content/uploads/2025/07/Logo-med-navnetraek-768x246.png"
                        width="120"
                        alt="Black Capital Technology"
                        style="display:block;border:0;outline:none;text-decoration:none;height:auto;max-width:120px;"
                      />
                    </td>
                    <td align="right" style="vertical-align:middle;">
                      <div
                        style="
                          font-family:Arial, Helvetica, sans-serif;
                          color:#ffffff;
                          font-size:12px;
                          letter-spacing:0.6px;
                          text-transform:uppercase;
                        "
                      >
                        Onboarding
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Hero -->
            <tr>
              <td
                style="
                  background:#ffffff;
                  padding:28px 24px 18px 24px;
                  border-left:1px solid #e6e9ff;
                  border-right:1px solid #e6e9ff;
                "
              >
                <div style="font-family:Arial, Helvetica, sans-serif;color:#0b1026;">
                  <div style="font-size:22px;line-height:28px;font-weight:700;color:#1a2a74;margin:0 0 6px 0;">
                    Velkommen til Black Capital Technology
                  </div>
                  <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0;">
                    Kære <strong>{{ employee_first_name }}</strong>,
                  </div>

                  <div style="height:12px;line-height:12px;font-size:12px;">&nbsp;</div>

                  <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0;">
                    Vi er meget glade for at kunne byde dig velkommen til Black Capital Technology.
                    Det betyder meget for os, at du har valgt at blive en del af virksomheden, og vi
                    ser frem til at arbejde sammen med dig.
                  </div>
                </div>
              </td>
            </tr>

            <!-- Mission / context card -->
            <tr>
              <td
                style="
                  background:#ffffff;
                  padding:0 24px 18px 24px;
                  border-left:1px solid #e6e9ff;
                  border-right:1px solid #e6e9ff;
                "
              >
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                  <tr>
                    <td
                      style="
                        background:#f0f2ff;
                        border:1px solid #e1e6ff;
                        border-radius:14px;
                        padding:16px 16px;
                      "
                    >
                      <div style="font-family:Arial, Helvetica, sans-serif;">
                        <div style="font-size:13px;line-height:20px;color:#3a4160;margin:0;">
                          BCT er nu blevet en international virksomhed, der bygger <strong>operationel AI</strong> til virksomheder
                          inden for energi, industri og teknologi. For os handler kunstig intelligens ikke om at eksperimentere
                          for at få synlighed, men om løsninger, der fungerer i praksis – også i krævende og driftskritiske miljøer.
                        </div>
                        <div style="height:10px;line-height:10px;font-size:10px;">&nbsp;</div>
                        <div style="font-size:13px;line-height:20px;color:#3a4160;margin:0;">
                          Vi arbejder tæt sammen med vores kunder, sætter os ind i deres virkelighed, leverer struktur, fremdrift og målbar værdi – og vi arbejder hurtigt!
                        </div>
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Culture -->
            <tr>
              <td
                style="
                  background:#ffffff;
                  padding:0 24px 18px 24px;
                  border-left:1px solid #e6e9ff;
                  border-right:1px solid #e6e9ff;
                "
              >
                <div style="font-family:Arial, Helvetica, sans-serif;color:#0b1026;">
                  <div style="font-size:16px;line-height:22px;font-weight:700;color:#1a2a74;margin:0 0 8px 0;">
                    Kultur og forventninger
                  </div>
                  <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0;">
                    Når du starter hos os, bliver du en del af et miljø med høje ambitioner og tydelige forventninger.
                    Vi kombinerer professionalisme og kvalitet med en kultur præget af:
                  </div>

                  <div style="height:10px;line-height:10px;font-size:10px;">&nbsp;</div>

                  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                    <tr>
                      <td style="font-family:Arial, Helvetica, sans-serif;font-size:14px;line-height:22px;color:#3a4160;">
                        • Tillid og ansvar<br />
                        • Effektivitet<br />
                        • Direkte kommunikation<br />
                        • Struktur og fremdrift<br />
                        • Målbar værdi for kunden
                      </td>
                    </tr>
                  </table>
                </div>
              </td>
            </tr>

            <!-- Onboarding timeline -->
            <tr>
              <td
                style="
                  background:#ffffff;
                  padding:0 24px 18px 24px;
                  border-left:1px solid #e6e9ff;
                  border-right:1px solid #e6e9ff;
                "
              >
                <div style="font-family:Arial, Helvetica, sans-serif;color:#0b1026;">
                  <div style="font-size:16px;line-height:22px;font-weight:700;color:#1a2a74;margin:0 0 8px 0;">
                    Opstart (første 2 uger)
                  </div>

                  <!-- Week 1 -->
                  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 10px 0;">
                    <tr>
                      <td width="44" valign="top" style="padding-top:2px;">
                        <div
                          style="
                            width:36px;height:36px;border-radius:10px;
                            background:#1a2a74;color:#ffffff;
                            font-family:Arial, Helvetica, sans-serif;
                            font-size:12px;line-height:36px;text-align:center;font-weight:700;
                          "
                        >
                          U1
                        </div>
                      </td>
                      <td valign="top" style="padding-left:10px;">
                        <div style="font-family:Arial, Helvetica, sans-serif;">
                          <div style="font-size:14px;line-height:20px;font-weight:700;color:#0b1026;margin:0 0 4px 0;">
                            Uge 1: Rammer, adgang og forventningsafstemning
                          </div>
                          <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0;">
                            Vi får de praktiske rammer på plads: udstyr, tekniske adgange, systemer og arbejdsredskaber.
                            Du får rundvisning, introduktion til vores arbejdsform og en præsentationsrunde.
                          </div>
                          <div style="height:8px;line-height:8px;font-size:8px;">&nbsp;</div>
                          <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0;">
                            Du introduceres til strategi, værdier og metode. Sammen med din nærmeste leder afklarer du projekt fra uge 2,
                            din rolle og din første konkrete leverance.
                          </div>
                        </div>
                      </td>
                    </tr>
                  </table>

                  <!-- Week 2 -->
                  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                    <tr>
                      <td width="44" valign="top" style="padding-top:2px;">
                        <div
                          style="
                            width:36px;height:36px;border-radius:10px;
                            background:#1a2a74;color:#ffffff;
                            font-family:Arial, Helvetica, sans-serif;
                            font-size:12px;line-height:36px;text-align:center;font-weight:700;
                          "
                        >
                          U2
                        </div>
                      </td>
                      <td valign="top" style="padding-left:10px;">
                        <div style="font-family:Arial, Helvetica, sans-serif;">
                          <div style="font-size:14px;line-height:20px;font-weight:700;color:#0b1026;margin:0 0 4px 0;">
                            Uge 2: Aktiv deltagelse i projektarbejdet
                          </div>
                          <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0;">
                            Fra og med uge 2 forventes det, at du deltager aktivt i projektarbejdet. Du får definerede opgaver og ansvar,
                            tilpasset din rolle og erfaring, og du deltager i kundedialog, analyser og leverancer.
                            Læring sker i praksis – med støtte fra leder og kolleger.
                          </div>
                        </div>
                      </td>
                    </tr>
                  </table>
                </div>
              </td>
            </tr>

            <!-- Follow-up meetings -->
            <tr>
              <td
                style="
                  background:#ffffff;
                  padding:0 24px 18px 24px;
                  border-left:1px solid #e6e9ff;
                  border-right:1px solid #e6e9ff;
                "
              >
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                  <tr>
                    <td
                      style="
                        background:#ffffff;
                        border:1px solid #e6e9ff;
                        border-radius:14px;
                        padding:16px;
                      "
                    >
                      <div style="font-family:Arial, Helvetica, sans-serif;">
                        <div style="font-size:16px;line-height:22px;font-weight:700;color:#1a2a74;margin:0 0 8px 0;">
                          Opfølgning i kalenderen
                        </div>
                        <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0 0 10px 0;">
                          For at sikre god opfølgning planlægger vi allerede i uge 1 en struktureret samtaleplan i din kalender sammen med din nærmeste leder:
                        </div>

                        <div style="font-size:14px;line-height:22px;color:#3a4160;">
                          • Samtale i slutningen af uge 1<br />
                          • Samtale i slutningen af uge 2<br />
                          • Opfølgningssamtale efter 30 dage<br />
                          • Opfølgningssamtale efter 60 dage<br />
                          • Opfølgningssamtale efter 90 dage
                        </div>

                        <div style="height:10px;line-height:10px;font-size:10px;">&nbsp;</div>

                        <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0;">
                          Disse møder bruges til at evaluere opstartsperioden, afklare forventninger, give feedback og sikre, at du udvikler dig i tråd med rollen og virksomhedens behov.
                        </div>
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Buddy -->
            <tr>
              <td
                style="
                  background:#ffffff;
                  padding:0 24px 18px 24px;
                  border-left:1px solid #e6e9ff;
                  border-right:1px solid #e6e9ff;
                "
              >
                <div style="font-family:Arial, Helvetica, sans-serif;">
                  <div style="font-size:16px;line-height:22px;font-weight:700;color:#1a2a74;margin:0 0 8px 0;">
                    Buddy
                  </div>

                  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                    <tr>
                      <td
                        style="
                          background:#f0f2ff;
                          border:1px dashed #cfd7ff;
                          border-radius:14px;
                          padding:14px 16px;
                        "
                      >
                        <div style="font-family:Arial, Helvetica, sans-serif;">
                          <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0;">
                            {% if buddy_name %}Din buddy er: <strong>{{ buddy_name }}</strong>{% else %}Din leder finder en buddy til dig og introducerer jer i løbet af den første uge.{% endif %}
                          </div>
                        </div>
                      </td>
                    </tr>
                  </table>

                  <div style="height:10px;line-height:10px;font-size:10px;">&nbsp;</div>

                  <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0;">
                    Buddyen er en erfaren kollega, som kender både vores metode og kultur godt. Buddyens rolle er at være et tilgængeligt og uformelt støttepunkt i de første 90 dage.
                    I uge 1 har I daglig kontakt, og videre i opstartsperioden mødes I jævnligt til sparring, spørgsmål og refleksion omkring projektarbejdet.
                  </div>
                </div>
              </td>
            </tr>

            <!-- 30/60/90 expectations -->
            <tr>
              <td
                style="
                  background:#ffffff;
                  padding:0 24px 22px 24px;
                  border-left:1px solid #e6e9ff;
                  border-right:1px solid #e6e9ff;
                "
              >
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                  <tr>
                    <td
                      style="
                        background:#ffffff;
                        border:1px solid #e6e9ff;
                        border-radius:14px;
                        padding:16px;
                      "
                    >
                      <div style="font-family:Arial, Helvetica, sans-serif;">
                        <div style="font-size:16px;line-height:22px;font-weight:700;color:#1a2a74;margin:0 0 8px 0;">
                          De første 90 dage
                        </div>
                        <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0;">
                          Selvom den formelle onboardingperiode primært varer to uger, følger vi dig tæt gennem de første 90 dage:
                        </div>

                        <div style="height:10px;line-height:10px;font-size:10px;">&nbsp;</div>

                        <div style="font-size:14px;line-height:22px;color:#3a4160;">
                          <strong>Inden for 30 dage:</strong> levere konkret værdi i et projekt<br />
                          <strong>Inden for 60 dage:</strong> arbejde med høj grad af selvstændighed<br />
                          <strong>Inden for 90 dage:</strong> kunne repræsentere BCT fuldt ud i tråd med din rolle
                        </div>

                        <div style="height:10px;line-height:10px;font-size:10px;">&nbsp;</div>

                        <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0;">
                          Vi ønsker, at du får en god start – både fagligt og socialt. Samtidig er vi tydelige om, at BCT er en virksomhed med høje ambitioner og klare forventninger.
                          Vi tror på at give ansvar tidligt, kombineret med støtte og tydelig opfølgning.
                        </div>
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Frokostordning -->
            <tr>
              <td
                style="
                  background:#ffffff;
                  padding:0 24px 22px 24px;
                  border-left:1px solid #e6e9ff;
                  border-right:1px solid #e6e9ff;
                "
              >
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                  <tr>
                    <td
                      style="
                        background:#f0f2ff;
                        border:1px solid #e1e6ff;
                        border-radius:14px;
                        padding:16px;
                      "
                    >
                      <div style="font-family:Arial, Helvetica, sans-serif;">
                        <div style="font-size:16px;line-height:22px;font-weight:700;color:#1a2a74;margin:0 0 8px 0;">
                          Frokostordning
                        </div>
                        <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0 0 10px 0;">
                          Vi har en fælles frokostordning gennem <strong>Kanpla</strong>. Opret din profil, inden du starter, så du er klar fra dag ét:
                        </div>

                        <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                          <tr>
                            <td bgcolor="#1a2a74" style="border-radius:999px;">
                              <a
                                href="https://kanpla.dk/join/7V1OHsMrvGMck8Iorb46"
                                target="_blank"
                                style="display:inline-block;padding:10px 16px;font-family:Arial,Helvetica,sans-serif;
                                       font-size:14px;line-height:18px;font-weight:700;color:#ffffff;text-decoration:none;
                                       border-radius:999px;"
                              >
                                Opret profil hos Kanpla
                              </a>
                            </td>
                          </tr>
                        </table>

                        <div style="height:12px;line-height:12px;font-size:12px;">&nbsp;</div>

                        <div style="font-size:14px;line-height:22px;color:#3a4160;">
                          • BCT betaler <strong>40&nbsp;%</strong> af kuvertprisen – din egenbetaling trækkes i bruttolønnen, så du opnår en skattebesparelse<br />
                          • Frokost bestilles på siden – <strong>senest kl. 12 dagen før</strong><br />
                          • Du kan sætte automatisk bestilling op, så du ikke skal huske det hver dag<br />
                          • Vi er fælles om at rydde op efter frokost
                        </div>
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Fitness -->
            <tr>
              <td
                style="
                  background:#ffffff;
                  padding:0 24px 22px 24px;
                  border-left:1px solid #e6e9ff;
                  border-right:1px solid #e6e9ff;
                "
              >
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                  <tr>
                    <td
                      style="
                        background:#ffffff;
                        border:1px solid #e6e9ff;
                        border-radius:14px;
                        padding:16px;
                      "
                    >
                      <div style="font-family:Arial, Helvetica, sans-serif;">
                        <div style="font-size:16px;line-height:22px;font-weight:700;color:#1a2a74;margin:0 0 8px 0;">
                          Fitness (Fitness United)
                        </div>
                        <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0 0 10px 0;">
                          Vi har en firmaaftale med <strong>Fitness United</strong>, som ligger ca. 200 meter fra kontoret – medlemskabet er
                          <strong>gratis for dig</strong> som medarbejder. Centret har alt det nødvendige – styrketræning, holdtræning, sauna m.m. –
                          og et bredt miljø med plads til alle træningsniveauer. Vil du meldes til, så svar på denne mail, så sørger vi for resten.
                        </div>
                        <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0 0 10px 0;">
                          Medlemskabet giver også adgang til deres øvrige centre. På Grønlandstorvet tilbyder de bl.a. <strong>WAVE-træning</strong>:
                          cirkeltræning med armbånd, hvor maskinerne automatisk tilpasser belastningen til dit niveau – en god indgang, hvis man er ny eller ønsker mere guidet træning.
                        </div>
                        <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0;">
                          Bliver vi nok på sigt, tager vi dialogen med centerlederen om egne firmahold eller faste hold på bestemte dage. Indtil da benytter vi de åbne hold.
                        </div>
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Parkering -->
            <tr>
              <td
                style="
                  background:#ffffff;
                  padding:0 24px 22px 24px;
                  border-left:1px solid #e6e9ff;
                  border-right:1px solid #e6e9ff;
                "
              >
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                  <tr>
                    <td
                      style="
                        background:#ffffff;
                        border:1px solid #e6e9ff;
                        border-radius:14px;
                        padding:16px;
                      "
                    >
                      <div style="font-family:Arial, Helvetica, sans-serif;">
                        <div style="font-size:16px;line-height:22px;font-weight:700;color:#1a2a74;margin:0 0 8px 0;">
                          Parkering
                        </div>
                        <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0 0 10px 0;">
                          Vi har en erhvervsløsning hos <strong>EasyPark</strong>, som giver mulighed for en parkeringslicens til de grønne og gule zoner
                          – dvs. ingen betaling for daglig parkering i de områder. På kortet herunder kan du se zonerne; der er bl.a. også god mulighed
                          for at parkere nede ved broen, hvis man en dag skal ind til byen.
                        </div>

                        <img
                          src="https://www.aalborg.dk/media/msehlnsr/parkering-aalborg-betaling-2026-002.jpg?width=1056&amp;format=jpeg&amp;quality=80"
                          width="528"
                          alt="Kort over parkeringszoner i Aalborg (grøn, gul og rød zone)"
                          style="display:block;border:0;outline:none;width:100%;max-width:528px;height:auto;border-radius:10px;border:1px solid #e1e6ff;margin:0 0 10px 0;"
                        />


                        <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0 0 10px 0;">
                          • <strong>Pris:</strong> 5.157 kr./år (~430 kr./md.)<br />
                          • Betales månedligt via bruttolønsordning<br />
                          • Licensen kan flyttes til nyt registreringsnummer ved skift af bil
                        </div>

                        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                          <tr>
                            <td
                              style="
                                background:#f0f2ff;
                                border:1px solid #e1e6ff;
                                border-radius:10px;
                                padding:12px 14px;
                              "
                            >
                              <div style="font-family:Arial, Helvetica, sans-serif;font-size:13px;line-height:20px;color:#3a4160;">
                                <strong>Hvordan fungerer bruttolønsordningen?</strong><br />
                                Din løn før skat reduceres med ca. 430 kr./md. Til gengæld betaler du mindre i skat, så din reelle udgift bliver lavere
                                – i praksis ca. 235–270 kr./md. efter skat (afhængigt af trækprocent).
                              </div>
                            </td>
                          </tr>
                        </table>

                        <div style="height:10px;line-height:10px;font-size:10px;">&nbsp;</div>

                        <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0;">
                          Ønsker du en licens, så svar på denne mail med <strong>nummerplade</strong>, <strong>bilmærke</strong> og <strong>model</strong>,
                          så opretter vi den. Bemærk: der er ca. en uges behandlingstid, før licensen er aktiv.
                        </div>
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Hvad skal du nu? (NEW) -->
            <tr>
              <td
                style="
                  background:#ffffff;
                  padding:0 24px 22px 24px;
                  border-left:1px solid #e6e9ff;
                  border-right:1px solid #e6e9ff;
                "
              >
                <div style="font-family:Arial, Helvetica, sans-serif;color:#0b1026;">
                  <div style="font-size:16px;line-height:22px;font-weight:700;color:#1a2a74;margin:0 0 8px 0;">
                    Hvad skal du nu?
                  </div>
                  <div style="font-size:14px;line-height:22px;color:#3a4160;margin:0 0 14px 0;">
                    For at komme godt i gang, skal du lige klare de tre punkter herunder.
                  </div>
                </div>

                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                  <!-- STEP 1 (Slack) -->
                  <tr>
                    <td style="padding:0 0 12px 0;">
                      <table
                        role="presentation"
                        width="100%"
                        cellspacing="0"
                        cellpadding="0"
                        border="0"
                        style="border:1px solid #e6e9ff;border-radius:14px;overflow:hidden;"
                      >
                        <tr>
                          <td style="padding:16px 16px 14px 16px;">
                            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                              <tr>
                                <td width="48" valign="top" style="padding-right:12px;">
                                  <div style="width:40px;height:40px;border-radius:10px;background:#ffffff;border:1px solid #e6e9ff;display:flex;align-items:center;justify-content:center;">
                                    <img
                                      src="https://cdn.brandfetch.io/idJ_HhtG0Z/theme/dark/symbol.svg?c=1bxid64Mup7aczewSAYMX"
                                      width="24"
                                      height="24"
                                      alt="Slack"
                                      style="display:block;border:0;outline:none;"
                                    />
                                  </div>
                                </td>
                                <td valign="top">
                                  <div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:22px;font-weight:700;color:#0b1026;">
                                    1) Acceptér din Slack-invitation
                                  </div>
                                  <div style="height:6px;line-height:6px;font-size:6px;">&nbsp;</div>
                                  <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:22px;color:#3a4160;">
                                    Brug “Continue with Google” og vælg din BCT-konto.
                                  </div>

                                  <div style="height:12px;line-height:12px;font-size:12px;">&nbsp;</div>

                                  <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                                    <tr>
                                      <td bgcolor="#1a2a74" style="border-radius:999px;">
                                        <a
                                          href="https://slack.com/get-started"
                                          target="_blank"
                                          style="display:inline-block;padding:10px 16px;font-family:Arial,Helvetica,sans-serif;
                                                 font-size:14px;line-height:18px;font-weight:700;color:#ffffff;text-decoration:none;
                                                 border-radius:999px;"
                                        >
                                          Åbn Slack
                                        </a>
                                      </td>
                                    </tr>
                                  </table>

                                  <div style="height:12px;line-height:12px;font-size:12px;">&nbsp;</div>

                                  <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:22px;color:#3a4160;">
                                    Når du er inde, så send gerne et hurtigt <strong>hej</strong> i <strong>#general</strong>.
                                  </div>
                                </td>
                              </tr>
                            </table>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>

                  <!-- STEP 2 (Notion) -->
                  <tr>
                    <td style="padding:0 0 12px 0;">
                      <table
                        role="presentation"
                        width="100%"
                        cellspacing="0"
                        cellpadding="0"
                        border="0"
                        style="border:1px solid #e6e9ff;border-radius:14px;overflow:hidden;"
                      >
                        <tr>
                          <td style="padding:16px 16px 14px 16px;">
                            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                              <tr>
                                <td width="48" valign="top" style="padding-right:12px;">
                                  <div style="width:40px;height:40px;border-radius:10px;background:#0b0d0f;border:1px solid #0b0d0f;display:flex;align-items:center;justify-content:center;">
                                    <img
                                      src="https://cdn.brandfetch.io/idPYUoikV7/theme/light/symbol.svg?c=1bxid64Mup7aczewSAYMX"
                                      width="24"
                                      height="24"
                                      alt="Notion"
                                      style="display:block;border:0;outline:none;"
                                    />
                                  </div>
                                </td>
                                <td valign="top">
                                  <div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:22px;font-weight:700;color:#0b1026;">
                                    2) Læs onboarding-siden på Notion
                                  </div>
                                  <div style="height:6px;line-height:6px;font-size:6px;">&nbsp;</div>
                                  <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:22px;color:#3a4160;">
                                    Log ind med din BCT Google-konto og gå til onboarding-siden.
                                  </div>

                                  <div style="height:12px;line-height:12px;font-size:12px;">&nbsp;</div>

                                  <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                                    <tr>
                                      <td bgcolor="#1a2a74" style="border-radius:999px;">
                                        <a
                                          href="https://www.notion.so/blackcapitaltechnology/Onboarding-530faee1ad5c4f90b51406acac896146?source=copy_link"
                                          target="_blank"
                                          style="display:inline-block;padding:10px 16px;font-family:Arial,Helvetica,sans-serif;
                                                 font-size:14px;line-height:18px;font-weight:700;color:#ffffff;text-decoration:none;
                                                 border-radius:999px;"
                                        >
                                          Åbn onboarding-side
                                        </a>
                                      </td>
                                    </tr>
                                  </table>
                                </td>
                              </tr>
                            </table>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>

                  <!-- STEP 3 (Leader invites) -->
                  <tr>
                    <td style="padding:0;">
                      <table
                        role="presentation"
                        width="100%"
                        cellspacing="0"
                        cellpadding="0"
                        border="0"
                        style="border:1px solid #e6e9ff;border-radius:14px;overflow:hidden;"
                      >
                        <tr>
                          <td style="padding:16px 16px 14px 16px;">
                            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                              <tr>
                                <td width="48" valign="top" style="padding-right:12px;">
                                  <div style="width:40px;height:40px;border-radius:10px;background:#f0f2ff;border:1px solid #e1e6ff;display:flex;align-items:center;justify-content:center;">
                                    <div style="font-family:Arial,Helvetica,sans-serif;font-weight:800;color:#1a2a74;font-size:16px;line-height:16px;">
                                      ✓
                                    </div>
                                  </div>
                                </td>
                                <td valign="top">
                                  <div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:22px;font-weight:700;color:#0b1026;">
                                    3) Invites til værktøjer
                                  </div>
                                  <div style="height:6px;line-height:6px;font-size:6px;">&nbsp;</div>
                                  <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:22px;color:#3a4160;">
                                    Din nærmeste leder vil invitere dig til relevante værktøjer som <strong>GitHub</strong>, <strong>Figma</strong> og <strong>Cursor</strong>.
                                  </div>
                                  <div style="height:8px;line-height:8px;font-size:8px;">&nbsp;</div>
                                  <div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:18px;color:#6f78a8;">
                                    Hvis du ikke har modtaget invites inden for de første dage, så svar på denne mail.
                                  </div>
                                </td>
                              </tr>
                            </table>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Footer / closing -->
            <tr>
              <td
                style="
                  background:#1a2a74;
                  padding:22px 24px;
                  border-radius:0 0 16px 16px;
                "
              >
                <div style="font-family:Arial, Helvetica, sans-serif;color:#ffffff;">
                  <div style="font-size:14px;line-height:22px;margin:0;">
                    Vi ser frem til at have dig med på holdet og til at bygge videre sammen.
                  </div>
                  <div style="height:10px;line-height:10px;font-size:10px;">&nbsp;</div>
                  <div style="font-size:14px;line-height:22px;margin:0;font-weight:700;">
                    Velkommen til Black Capital Technology – og HELD OG LYKKE!
                  </div>
                  <div style="height:14px;line-height:14px;font-size:14px;">&nbsp;</div>
                  <div style="font-size:14px;line-height:22px;margin:0;">
                    Bedste hilsen<br />
                    <strong>Malthe og Stefan</strong>, grundlæggere<br />
                    Black Capital Technology
                  </div>

                  <div style="height:14px;line-height:14px;font-size:14px;">&nbsp;</div>

                  <div style="font-size:12px;line-height:18px;opacity:0.9;">
                    Tip: Er noget uklart, så svar bare på denne mail – vi hjælper hurtigt.
                  </div>
                </div>
              </td>
            </tr>

            <!-- Small footer note -->
            <tr>
              <td align="center" style="padding:14px 6px 0 6px;">
                <div style="font-family:Arial, Helvetica, sans-serif;font-size:11px;line-height:16px;color:#7078a3;">
                  © Black Capital Technology
                </div>
              </td>
            </tr>
          </table>
          <!-- /Container -->
        </td>
      </tr>
    </table>
  </body>
</html>
"""
