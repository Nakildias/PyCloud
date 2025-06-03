// static/js/localetime_formatter.js - MODIFIED FOR CUSTOM FORMATTING

document.addEventListener('DOMContentLoaded', function() {
    // Function to format ISO 8601 string to the user's local time
    // Accepts an optional format type parameter
    function formatLocalTime(isoString, formatType = 'default') { // Added formatType parameter with a default
        if (!isoString) {
            console.warn("Empty string provided to formatLocalTime.");
            return "Invalid Date (Empty)";
        }

        let date = null;

        try {
            // Attempt parsing with Date constructor first
            // This should work correctly with the valid ISO 8601 strings
            // produced by the corrected localetime filter in main.py
            date = new Date(isoString);

            // Fallback/Robustness: If parsing with Date constructor fails,
            // you can keep the alternative regex parsing logic from the previous step here
            // if you encountered issues with certain browsers or formats, but for
            // standard ISO strings (like YYYY-MM-DDTHH:MM:SS+00:00), the Date constructor is preferred.
            // For brevity here, assuming the Date constructor is sufficient with the corrected ISO format.
            // If you need the extra parsing logic, ensure it's integrated correctly here.

            // --- Keep the invalid date check after parsing ---
            if (isNaN(date.getTime())) {
                console.error("Date is invalid after parsing attempts:", isoString);
                // You might want to return a specific error string based on the formatType
                return "Invalid Date"; // Generic error for now
            }

            // --- Apply formatting based on formatType ---
            if (formatType === 'YYYY-MM-DD HH:MM') {
                // Manually construct the string for the desired format
                const year = date.getFullYear();
                // getMonth() is 0-indexed, add 1 and pad with '0'
                const month = ('0' + (date.getMonth() + 1)).slice(-2);
                const day = ('0' + date.getDate()).slice(-2);
                const hours = ('0' + date.getHours()).slice(-2);
                const minutes = ('0' + date.getMinutes()).slice(-2);
                return `${year}-${month}-${day} ${hours}:${minutes}`;
            } else { // 'default' format (using toLocaleString)
                // Use toLocaleString for a more locale-aware and potentially verbose format
                const options = {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: true // Use 12-hour format with AM/PM
                };
                return date.toLocaleString(undefined, options); // 'undefined' uses the user's default locale
            }
            // --- END MODIFIED FORMATTING ---

        } catch (e) {
            console.error("Error formatting or parsing date:", isoString, e);
            return "Error Formatting Date";
        }
    }

    // Find all elements with the 'data-timestamp' attribute
    const timestampElements = document.querySelectorAll('[data-timestamp]');

    // Iterate through the elements and update their text content
    timestampElements.forEach(element => {
        const isoString = element.getAttribute('data-timestamp');
        // --- MODIFIED: Get data-format attribute ---
        // Read the value of the data-format attribute, default to 'default' if not present
        const formatType = element.getAttribute('data-format') || 'default';
        // --- END MODIFIED ---
        if (isoString) {
            // Pass the format type to the formatting function
            const localTimeString = formatLocalTime(isoString, formatType); // Pass formatType
            element.textContent = localTimeString; // Replace the content with the formatted time
            // Optional: You could set the title attribute here too if needed
        } else {
            // If data-timestamp is empty (e.g., null date from server), update the placeholder
            element.textContent = "Invalid Date (No Data)";
        }
    });
});
