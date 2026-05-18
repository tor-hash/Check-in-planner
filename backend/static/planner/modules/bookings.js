/* eslint-disable no-console */
/**
 * modules/bookings.js
 *
 * Thin client for the new server-side booking flow:
 *   - listFreeBusy({from,to,emails|team})   → busy intervals from Django
 *   - createBooking({managerId,personId,startsAt,...}) → creates the
 *     CheckInMeeting + Google event in one round-trip
 *   - cancelBooking(id)                     → cancels DB row + Google event
 *
 * The legacy in-page booking modal now calls this module, so event creation
 * goes through Django instead of calling Google Calendar directly.
 */
(function () {
  "use strict";

  if (!window.Planner || typeof window.Planner.register !== "function") {
    return;
  }

  window.Planner.register("bookings", function (api) {
    async function loadFreeBusy({ from, to, emails, team }) {
      const response = await api.freeBusy({ from, to, emails, team });
      return response.calendars || {};
    }

    async function loadRotation(upcoming = 4) {
      const response = await api.getRotation(upcoming);
      return response.sessions || [];
    }

    async function listMyBookings(managerId) {
      const response = await api.listBookings({ managerId, status: "scheduled" });
      return response.bookings || [];
    }

    async function book({ managerId, personId, startsAt, durationMinutes, title, agenda }) {
      return api.createBooking({
        managerId,
        personId,
        startsAt,
        durationMinutes: durationMinutes || 30,
        title: title || "Check-in samtale",
        agenda: agenda || "",
      });
    }

    async function cancel(bookingId) {
      return api.cancelBooking(bookingId);
    }

    return { loadFreeBusy, loadRotation, listMyBookings, book, cancel };
  });
})();
